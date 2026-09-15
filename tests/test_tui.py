"""
##################################################################################
#
# conClaude by Marcin Orlowski
# The only Claude Code session manager you need.
#
# @author    Marcin Orlowski <mail@marcinOrlowski.com>
# Copyright  ©2026 Marcin Orlowski <MarcinOrlowski.com>
# @link      https://github.com/MarcinOrlowski/conclaude
#
##################################################################################
"""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest
from qrcat import render_qr
from textual.color import Color, ColorParseError
from textual.containers import VerticalScroll
from textual.geometry import Region
from textual.pilot import Pilot
from textual.theme import BUILTIN_THEMES
from textual.widgets import DataTable, Static

import conclaude.core.store
import conclaude.tui.app
from conclaude import __author__, __description__, __title__, __url__, __version__
from conclaude.core.cache import Cache
from conclaude.core.format import Formatter
from conclaude.core.model import Figures, TrashEntry
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from conclaude.core.trash import trash_session
from conclaude.tui.about import QR_BORDER, QR_ERROR, AboutScreen
from conclaude.tui.app import ConclaudeApp, FullScreen, MainScreen, TrashScreen
from conclaude.tui.panes import (
    ALL_DAYS,
    ALL_PROJECTS,
    DaysPane,
    DetailsPane,
    EntriesPane,
    EntryPane,
    FilterBox,
    Lines,
    Lister,
    ProjectsPane,
    SessionsPane,
    Table,
    TitleBar,
    TooSmall,
)
from tests.fabricate import (
    FakeClaude,
    FakeProc,
    dump_line,
    encode_project,
    new_id,
    prompt_record,
    session_records,
    snapshot,
)

WIDE = (140, 40)


def columns(table: DataTable) -> list[str]:
    """The column labels, left to right."""
    return [str(column.label) for column in table.columns.values()]


def rows(table: DataTable) -> list[str]:
    """The session ids, top to bottom."""
    return [str(row.key.value) for row in table.ordered_rows]


def left_on_view(app: ConclaudeApp) -> bool:
    """Whether the left pane is on view.

    It goes out of view with the box around it, so its own ``display`` says
    nothing. The box is the thing to look at.
    """
    return bool(app.screen.query_one("#left").display)


def one_column(app: ConclaudeApp) -> bool:
    """Whether the panes are in one column, one over the other."""
    return "-stacked" in app.screen.query_one("#body").classes


def pane_boxes(app: ConclaudeApp) -> tuple[Region, Region, Region]:
    """Where the three panes are: the left one, the table, the lower one."""
    screen = app.screen
    return (
        screen.query_one("#left").region,
        screen.query_one(Table).region,
        screen.query_one(Lines).region,
    )


def shown_keys(app: ConclaudeApp) -> dict[str, str]:
    """What the footer lists right now: key to description."""
    return {
        key: active.binding.description
        for key, active in app.active_bindings.items()
        if active.binding.show
    }


def three_sessions(fake: FakeClaude) -> tuple[str, str, str]:
    """Two sessions in ``/p/a`` and one in ``/p/b``, newest first by last use."""
    a1, a2, b1 = new_id(), new_id(), new_id()
    fake.transcript(
        "/p/a", a1, session_records(a1, "/p/a", custom_title="A1"), mtime=3000
    )
    fake.transcript(
        "/p/a", a2, session_records(a2, "/p/a", custom_title="A2"), mtime=2000
    )
    fake.transcript(
        "/p/b", b1, session_records(b1, "/p/b", custom_title="B1"), mtime=1000
    )
    return a1, a2, b1


def painted_lines(pane: Lines, lines: list[tuple[str, str]]) -> list[str]:
    """The lines as the pane paints them: one column of labels, each value cut to fit."""
    width = max(len(label) for label, _ in lines) + 1
    room = pane.scrollable_content_region.width - width - 1
    return [
        f"{(label + ':').ljust(width)} {pane.fmt.fit(value, room)}"
        for label, value in lines
    ]


async def test_three_panes_projects_left_sessions_upper_right_details_lower_right(
    fake: FakeClaude, settings: Settings
) -> None:
    """Three panes: projects left, sessions upper right, details lower right."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        header = app.query_one(TitleBar).region
        projects = app.query_one(ProjectsPane).region
        sessions = app.query_one(SessionsPane).region
        details = app.query_one(DetailsPane).region

    assert (header.x, header.y, header.width, header.height) == (0, 0, WIDE[0], 1)
    assert projects.x == 0
    assert projects.right == sessions.x == details.x
    assert projects.y == sessions.y == header.bottom
    assert sessions.bottom == details.y
    assert projects.bottom >= details.bottom
    assert settings.projects_pane_min_width <= projects.width
    assert projects.width <= settings.projects_pane_max_width


async def test_a_narrow_window_puts_the_three_panes_in_one_column(
    fake: FakeClaude, settings: Settings
) -> None:
    """A narrow window holds the panes in one column, and a wide one in two again."""
    three_sessions(fake)
    narrow = (settings.stack_panes_below - 1, 30)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(*narrow)
        await pilot.pause()
        projects, sessions, details = pane_boxes(app)
        stacked = one_column(app), left_on_view(app)
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        wide_boxes = pane_boxes(app)
        wide = one_column(app), left_on_view(app)

    assert stacked == (True, True)
    # Every pane keeps the full width, and they sit one over the other
    assert projects.x == sessions.x == details.x == 0
    assert projects.width == sessions.width == details.width == narrow[0]
    assert projects.bottom == sessions.y
    assert sessions.bottom == details.y
    # Two columns again, with no restart
    assert wide == (False, True)
    assert wide_boxes[0].right == wide_boxes[1].x == wide_boxes[2].x
    assert wide_boxes[0].y == wide_boxes[1].y


async def test_every_pane_stays_on_view_in_the_narrowest_window(
    fake: FakeClaude, settings: Settings
) -> None:
    """No pane ever goes out of view on its own: the column holds all three."""
    three_sessions(fake)
    narrow = (settings.min_width, settings.min_height)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(*narrow)
        await pilot.pause()
        table = app.query_one(SessionsPane)
        shown = left_on_view(app), one_column(app), table.display
        projects, sessions, details = pane_boxes(app)
        listed = rows(table)

    assert shown == (True, True, True)
    assert projects.x == sessions.x == details.x == 0
    assert projects.width == sessions.width == details.width == narrow[0]
    assert len(listed) == 3


async def test_a_window_too_small_shows_a_plain_message_in_place_of_the_panes(
    fake: FakeClaude, settings: Settings
) -> None:
    """Too small to be of use: a plain message takes the place of the whole layout."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        message = app.query_one(TooSmall)
        body = app.query_one("#body")
        wide = (body.display, message.display)
        await pilot.resize_terminal(settings.min_width - 1, WIDE[1])
        await pilot.pause()
        thin = (body.display, message.display)
        await pilot.resize_terminal(WIDE[0], settings.min_height - 1)
        await pilot.pause()
        short = (body.display, message.display)
        text = str(message.render())
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        back = (body.display, message.display)

    assert wide == (True, False)
    assert thin == (False, True)
    assert short == (False, True)
    assert "Window too small" in text
    assert f"{settings.min_width} x {settings.min_height}" in text
    assert back == (True, False)


async def test_q_still_quits_while_the_window_is_too_small(
    fake: FakeClaude, settings: Settings
) -> None:
    """A window with no room for the panes does not trap the user: q still quits."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(settings.min_width - 1, settings.min_height - 1)
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        running = app.is_running

    assert running is False


async def test_the_focus_never_goes_missing_when_the_window_changes_size(
    fake: FakeClaude, settings: Settings
) -> None:
    """One column keeps the focus where it was. A window too small hands it to the table."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("tab", "tab")
        await pilot.pause()
        on_details = type(app.focused)
        await pilot.resize_terminal(settings.stack_panes_below - 1, 20)
        await pilot.pause()
        stacked = type(app.focused)
        await pilot.resize_terminal(settings.min_width - 1, settings.min_height - 1)
        await pilot.pause()
        smaller = type(app.focused)
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        back = type(app.focused)

    assert on_details is DetailsPane
    # No pane goes out of view here, so the focus has no reason to move
    assert stacked is DetailsPane
    # The panes went with the layout, so the table holds the keys
    assert smaller is SessionsPane
    assert back is SessionsPane


async def test_the_widths_that_shape_the_layout_come_from_the_settings(
    fake: FakeClaude, settings: Settings
) -> None:
    """The breakpoints are settings, never numbers in the code."""
    three_sessions(fake)
    settings.stack_panes_below = WIDE[0] + 10
    settings.min_width = WIDE[0] - 10
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        shaped = one_column(app), left_on_view(app)
        body = app.query_one("#body").display
        await pilot.resize_terminal(settings.min_width - 1, WIDE[1])
        await pilot.pause()
        smaller = app.query_one("#body").display, app.query_one(TooSmall).display

    assert shaped == (True, True)
    assert body is True
    assert smaller == (False, True)


async def test_enter_on_a_session_opens_its_details_over_the_whole_window(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'enter' key on a session opens the details full screen, and 'escape' closes them."""
    a1, _a2, _b1 = three_sessions(fake)
    narrow = (settings.stack_panes_below - 1, 20)
    app = ConclaudeApp(settings)
    async with app.run_test(size=narrow) as pilot:
        await pilot.pause()
        await pilot.press("tab", "enter")
        await pilot.pause()
        box = app.screen.query_one(Lines)
        opened = type(app.screen), str(box.border_title), box.region.width
        text = box.text
        await pilot.press("escape")
        await pilot.pause()
        closed = type(app.screen), type(app.focused)

    assert opened == (FullScreen, "Details", narrow[0])
    assert re.search(rf"^Id: +{a1}$", text, re.M)
    assert re.search(r"^Title: +A1 ", text, re.M)
    assert closed == (MainScreen, SessionsPane)


async def test_in_the_trash_the_panes_follow_the_same_widths_and_enter_opens_an_entry(
    fake: FakeClaude, settings: Settings
) -> None:
    """Trash mode takes the same shapes, and 'enter' opens one entry full screen."""
    _a1, _a2, b1 = three_sessions(fake)
    SessionStore(settings).trash(b1)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        wide = one_column(app), left_on_view(app)
        await pilot.resize_terminal(settings.stack_panes_below - 1, 20)
        await pilot.pause()
        narrow = (one_column(app), left_on_view(app), type(app.focused))
        await pilot.press("enter")
        await pilot.pause()
        box = app.screen.query_one(Lines)
        opened = type(app.screen), str(box.border_title)
        text = box.text
        await pilot.press("escape")
        await pilot.pause()
        closed = type(app.screen), type(app.focused)

    assert wide == (False, True)
    assert narrow == (True, True, EntriesPane)
    assert opened == (FullScreen, "Entry")
    assert re.search(rf"^Session: +{b1}$", text, re.M)
    assert closed == (TrashScreen, EntriesPane)


async def test_projects_pane_lists_all_projects_first_and_hides_empty_ones(
    fake: FakeClaude, settings: Settings
) -> None:
    """Projects pane lists 'All projects' first and hides projects with no session."""
    three_sessions(fake)
    fake.project("/p/empty")
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        prompts = [str(option.prompt) for option in pane.options]
        ids = [option.id for option in pane.options]
        selected = pane.selected_path

    assert prompts == [ALL_PROJECTS, "/p/a", "/p/b"]
    assert ids == [None, "/p/a", "/p/b"]
    assert selected is None


async def test_all_projects_shows_every_session_with_a_project_column(
    fake: FakeClaude, settings: Settings
) -> None:
    """All projects shows every session, newest first, with a Project column."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        labels = columns(table)
        listed = rows(table)
        projects = [str(table.get_cell(sid, "project")) for sid in listed]

    assert labels == ["Sts", "Title", "Last used ▼", "Size", "Msgs", "Project"]
    assert listed == [a1, a2, b1]
    assert projects == ["/p/a", "/p/a", "/p/b"]


async def test_choosing_a_project_shows_only_its_sessions(
    fake: FakeClaude, settings: Settings
) -> None:
    """Choosing a project shows only its sessions, and the Project column goes."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        table = app.query_one(SessionsPane)
        in_a = rows(table), columns(table), app.query_one(ProjectsPane).selected_path
        await pilot.press("down")
        await pilot.pause()
        in_b = rows(table), app.query_one(ProjectsPane).selected_path

    assert in_a == ([a1, a2], ["Sts", "Title", "Last used ▼", "Size", "Msgs"], "/p/a")
    assert in_b == ([b1], "/p/b")


async def test_the_columns_hold_state_title_last_used_size_and_an_empty_turn_count(
    fake: FakeClaude, settings: Settings
) -> None:
    """The columns hold the state, the title, last used, size and an empty turn count."""
    sid = new_id()
    fake.transcript("/p/x", sid, session_records(sid, "/p/x", custom_title="Hello"))
    fake.sidecar("/p/x", sid, bytes_each=10)
    session = SessionStore(settings).find_session(sid)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        cells = [
            str(table.get_cell(sid, key))
            for key in ("state", "title", "last_used", "size", "msgs")
        ]

    assert cells == [
        "---",
        "Hello",
        fmt.timestamp(session.last_used),
        fmt.size(session.size),
        "",
    ]


async def test_the_state_column_holds_one_slot_for_every_state(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """The state column holds one slot per state, and the title keeps all its room.

    A state that is on shows its letter, one that is off shows a dash. A session
    in two states shows two letters, each in its own slot.
    """
    running, parent, child, twin, broken = (new_id() for _ in range(5))
    fake.transcript(
        "/p/x", running, session_records(running, "/p/x", custom_title="Run")
    )
    fake.marker(100, running, 5000, name="dev:app")
    proc.stat(100, 5000)
    fake.transcript("/p/x", parent, session_records(parent, "/p/x", custom_title="Mum"))
    fake.transcript(
        "/p/x",
        child,
        session_records(child, "/p/x", copied_from=parent, custom_title="Kid"),
    )
    fake.transcript(
        "/p/x",
        twin,
        session_records(twin, "/p/x", copied_from=parent, custom_title="Two"),
    )
    fake.marker(200, twin, 6000, name="Twin")
    proc.stat(200, 6000)
    fake.transcript("/p/x", broken, raw=b"\xff\xfe")
    listed = (running, parent, child, twin, broken)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        states = {sid: str(table.get_cell(sid, "state")) for sid in listed}
        titles = {sid: str(table.get_cell(sid, "title")) for sid in listed[:4]}

    assert states == {
        running: "L--",
        parent: "---",
        child: "-F-",
        twin: "LF-",
        broken: "--D",
    }
    assert titles == {running: "dev:app", parent: "Mum", child: "Kid", twin: "Twin"}


async def test_the_details_pane_shows_the_session_under_the_cursor_in_full(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """The details pane shows the session under the cursor in full."""
    sid = new_id()
    fake.transcript(
        "/p/x",
        sid,
        session_records(sid, "/p/x", custom_title="Hello", branch="dev"),
    )
    fake.sidecar("/p/x", sid, agents=3)
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 36917)
    store = SessionStore(settings)
    session = store.find_session(sid)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(DetailsPane)
        text = pane.text
        static = app.query_one("#details-text", Static)
        painted = str(static.render())
        expected = painted_lines(pane, fmt.describe(store.details(sid)))

    assert painted == text
    assert text.splitlines() == expected
    assert f"Id:          {sid}" in text
    assert "Project:     /p/x  (from transcript)" in text
    assert re.search(r"^Folder: +\S+/claude/projects/-p-x$", text, re.M)
    assert "Git branch:  dev" in text
    assert f"Created:     {fmt.timestamp(session.created)}" in text
    assert f"Last used:   {fmt.timestamp(session.last_used)}" in text
    assert "Claude Code: 2.1.270" in text
    assert f"Transcript:  {fmt.size(session.transcript_size)}  {sid}.jsonl" in text
    assert (
        f"Sidecar:     {fmt.size(session.sidecar_size)}  {sid}  (3 subagent transcripts)"
        in text
    )
    assert f"Total:       {fmt.size(session.size)}" in text
    assert "Live:        yes  (pid 4242)" in text
    assert "Fork of:" not in text


async def test_the_details_of_a_fork_name_the_parent_and_the_inherited_bytes(
    fake: FakeClaude, settings: Settings
) -> None:
    """The details of a fork name the parent and the inherited bytes."""
    parent, child = new_id(), new_id()
    fake.transcript("/p/x", parent, mtime=1000)
    fake.transcript(
        "/p/x", child, session_records(child, "/p/x", copied_from=parent), mtime=2000
    )
    details = SessionStore(settings).details(child)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        text = app.query_one(DetailsPane).text

    assert details.inherited_bytes > 0
    assert f"Fork of:     {parent}" in text
    assert (
        f"Inherited:   {fmt.size(details.inherited_bytes)} came from the parent" in text
    )


async def test_moving_the_cursor_changes_the_details(
    fake: FakeClaude, settings: Settings
) -> None:
    """Moving the cursor changes the details."""
    a1, a2, _b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("tab", "down")
        await pilot.pause()
        table = app.query_one(SessionsPane)
        selected = table.selected_id
        text = app.query_one(DetailsPane).text

    assert selected == a2
    assert f"Id:          {a2}" in text
    assert a1 not in text


async def test_the_selection_is_a_session_id_that_survives_a_change_of_project(
    fake: FakeClaude, settings: Settings
) -> None:
    """The selection is a session id, so it survives a change of project."""
    _a1, _a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "down", "down")
        await pilot.pause()
        in_all = table.selected_id, table.cursor_row
        await pilot.press("shift+tab", "down", "down")
        await pilot.pause()
        in_b = table.selected_id, table.cursor_row, rows(table)

    assert in_all == (b1, 2)
    assert in_b == (b1, 0, [b1])


async def test_with_no_session_at_all_the_panes_are_empty_but_the_screen_works(
    fake: FakeClaude, settings: Settings
) -> None:
    """With no session at all the panes are empty but the screen works."""
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        prompts = [str(option.prompt) for option in app.query_one(ProjectsPane).options]
        table = app.query_one(SessionsPane)
        count, selected = table.row_count, table.selected_id
        text = app.query_one(DetailsPane).text
        await pilot.press("tab", "tab", "tab", "q")
        await pilot.pause()
        running = app.is_running

    assert prompts == [ALL_PROJECTS]
    assert (count, selected) == (0, None)
    assert text == "No session."
    assert running is False


def test_no_key_is_bound_on_the_app_or_the_screen() -> None:
    """No key is bound on the app or the screen: every key belongs to a pane."""
    assert "BINDINGS" not in ConclaudeApp.__dict__
    assert "BINDINGS" not in MainScreen.__dict__
    assert "BINDINGS" not in TrashScreen.__dict__
    panes = (ProjectsPane, SessionsPane, DetailsPane, DaysPane, EntriesPane, EntryPane)
    for pane in panes:
        keys = {binding.key for binding in pane.__dict__["BINDINGS"]}
        assert {"tab", "q", "r", "t", "question_mark"} <= keys, pane.__name__


async def test_the_footer_lists_the_keys_of_the_focused_pane_and_follows_focus(
    fake: FakeClaude, settings: Settings
) -> None:
    """The footer lists the keys of the focused pane and follows the focus."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        focus = [type(app.focused)]
        keys = [shown_keys(app)]
        for _ in range(3):
            await pilot.press("tab")
            await pilot.pause()
            focus.append(type(app.focused))
            keys.append(shown_keys(app))

    assert focus == [ProjectsPane, SessionsPane, DetailsPane, ProjectsPane]
    assert keys[0] == keys[3]
    assert keys[0] != keys[1]
    assert keys[0]["enter"] == "Sessions"
    assert keys[1]["enter"] == "Details"
    assert "enter" not in keys[2]
    for listed in keys:
        assert {"tab", "q"} <= set(listed)


async def test_enter_on_a_project_moves_into_its_sessions(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'enter' key on a project moves into its sessions."""
    a1, _a2, _b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        focused = type(app.focused)
        selected = app.query_one(SessionsPane).selected_id

    assert focused is SessionsPane
    assert selected == a1


async def test_q_quits_from_every_pane(fake: FakeClaude, settings: Settings) -> None:
    """The 'q' key quits from every pane."""
    three_sessions(fake)
    for tabs in range(3):
        app = ConclaudeApp(settings)
        async with app.run_test(size=WIDE) as pilot:
            await pilot.pause()
            await pilot.press(*(["tab"] * tabs), "q")
            await pilot.pause()
            running = app.is_running

        assert running is False, f"still running after q from pane {tabs}"


async def test_the_theme_in_effect_comes_from_the_settings(
    fake: FakeClaude, settings: Settings
) -> None:
    """The theme in effect comes from the settings."""
    settings.theme = "nord"
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        theme = app.theme

    assert theme == "nord"
    assert Settings().theme != "nord"


async def test_every_theme_the_library_ships_applies(
    fake: FakeClaude, settings: Settings
) -> None:
    """Every theme the library ships applies."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    applied = []
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        for name in sorted(BUILTIN_THEMES):
            app.theme = name
            await pilot.pause()
            applied.append(app.theme)

    assert applied == sorted(BUILTIN_THEMES)
    assert len(applied) >= 20


def state(table: SessionsPane) -> tuple[list[str], str | None, tuple[str, bool]]:
    """The rows, the selected id and the sort order, in one tuple."""
    return rows(table), table.selected_id, table.sorting


async def test_r_reloads_and_the_cursor_finds_its_session_by_id(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'r' key reloads. The cursor finds its session by id, not by row number."""
    a1, a2, _b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("down", "tab", "down")
        await pilot.pause()
        before = table.selected_id, table.cursor_row, rows(table)
        new = new_id()
        fake.transcript(
            "/p/a", new, session_records(new, "/p/a", custom_title="New"), mtime=4000
        )
        await pilot.press("r")
        await pilot.pause()
        after = table.selected_id, table.cursor_row, rows(table)
        project = app.query_one(ProjectsPane).selected_path
        text = app.query_one(DetailsPane).text

    assert before == (a2, 1, [a1, a2])
    assert after == (a2, 2, [new, a1, a2])
    assert project == "/p/a"
    assert f"Id:          {a2}" in text


async def test_after_a_reload_a_gone_session_hands_its_row_to_the_next_one(
    fake: FakeClaude, settings: Settings
) -> None:
    """After a reload a gone session hands its row to the one that replaced it."""
    a1, a2, b1 = three_sessions(fake)
    store = SessionStore(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "down")
        await pilot.pause()
        store.trash(a2)
        await pilot.press("r")
        await pilot.pause()
        middle_gone = table.selected_id, table.cursor_row, rows(table)
        store.trash(b1)
        await pilot.press("r")
        await pilot.pause()
        last_gone = table.selected_id, table.cursor_row, rows(table)

    assert middle_gone == (b1, 1, [a1, b1])
    assert last_gone == (a1, 0, [a1])


async def test_after_a_reload_a_gone_project_hands_its_line_to_the_next_one(
    fake: FakeClaude, settings: Settings
) -> None:
    """After a reload a gone project hands its line to the one that replaced it."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        await pilot.press("down", "down")
        await pilot.pause()
        before = pane.selected_path
        SessionStore(settings).trash(b1)
        await pilot.press("r")
        await pilot.pause()
        prompts = [str(option.prompt) for option in pane.options]
        after = pane.selected_path, rows(app.query_one(SessionsPane))

    assert before == "/p/b"
    assert prompts == [ALL_PROJECTS, "/p/a"]
    assert after == ("/p/a", [a1, a2])


def sized_sessions(fake: FakeClaude) -> tuple[str, str, str]:
    """Three sessions whose order differs by last use, by title and by size.

    Last used: a1, a2, b1. Title: b1 (Alpha), a1 (Mid), a2 (Zed).
    Size: b1, a1, a2.
    """
    a1, a2, b1 = new_id(), new_id(), new_id()
    fake.transcript(
        "/p/a", a1, session_records(a1, "/p/a", custom_title="Mid"), mtime=3000
    )
    fake.transcript(
        "/p/a", a2, session_records(a2, "/p/a", custom_title="Zed"), mtime=2000
    )
    fake.transcript(
        "/p/b", b1, session_records(b1, "/p/b", custom_title="Alpha"), mtime=1000
    )
    fake.sidecar("/p/a", a1, bytes_each=100)
    fake.sidecar("/p/b", b1, bytes_each=5000)
    return a1, a2, b1


async def test_the_rows_start_at_last_used_newest_first_as_the_settings_say(
    fake: FakeClaude, settings: Settings
) -> None:
    """The rows start at last used, newest first, as the settings say."""
    a1, a2, b1 = sized_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        by_time = state(table), columns(table)

    settings.sort_column = "title"
    settings.sort_descending = False
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        by_title = state(table), columns(table)

    assert by_time == (
        ([a1, a2, b1], a1, ("last_used", True)),
        ["Sts", "Title", "Last used ▼", "Size", "Msgs", "Project"],
    )
    assert by_title == (
        ([b1, a1, a2], b1, ("title", False)),
        ["Sts", "Title ▲", "Last used", "Size", "Msgs", "Project"],
    )


async def test_o_orders_by_the_next_column_and_the_cursor_stays_on_its_session(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'o' key orders by the next column, 'O' turns it round. The cursor keeps its session."""
    a1, a2, b1 = sized_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "down")
        await pilot.pause()
        seen = [state(table)]
        for key in ("o", "O", "o", "o", "o", "o", "o"):
            await pilot.press(key)
            await pilot.pause()
            seen.append(state(table))
        marked = columns(table)

    assert seen == [
        ([a1, a2, b1], a2, ("last_used", True)),
        ([b1, a1, a2], a2, ("size", True)),
        ([a2, a1, b1], a2, ("size", False)),
        ([a1, a2, b1], a2, ("msgs", True)),
        ([a1, a2, b1], a2, ("project", False)),
        ([a1, a2, b1], a2, ("state", True)),
        ([b1, a1, a2], a2, ("title", False)),
        ([a1, a2, b1], a2, ("last_used", True)),
    ]
    assert marked == ["Sts", "Title", "Last used ▼", "Size", "Msgs", "Project"]


async def test_the_project_column_is_skipped_by_o_when_it_is_not_on_view(
    fake: FakeClaude, settings: Settings
) -> None:
    """The Project column is skipped by o when it is not on view."""
    sized_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("down", "tab")
        await pilot.pause()
        seen = []
        for _ in range(5):
            await pilot.press("o")
            await pilot.pause()
            seen.append(table.sorting[0])

    assert seen == ["size", "msgs", "state", "title", "last_used"]


async def test_a_click_on_a_header_orders_by_that_column_and_again_turns_it_round(
    fake: FakeClaude, settings: Settings
) -> None:
    """A click on a header orders by that column. A second click turns it round."""
    a1, a2, b1 = sized_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "down")
        await pilot.pause()
        # The border, the State column and the paddings take the columns before
        # this one, so x 7 is on the Title header.
        await pilot.click(SessionsPane, offset=(7, 1))
        await pilot.pause()
        once = state(table)
        await pilot.click(SessionsPane, offset=(7, 1))
        await pilot.pause()
        twice = state(table)

    assert once == ([b1, a1, a2], a2, ("title", False))
    assert twice == ([a2, a1, b1], a2, ("title", True))


async def test_slash_opens_a_box_that_narrows_the_sessions_as_you_type(
    fake: FakeClaude, settings: Settings
) -> None:
    """The '/' key opens a box. The sessions narrow by title as you type, case aside."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        box = app.query_one("#sessions-filter", FilterBox)
        at_start = box.display, "escape" in shown_keys(app)
        await pilot.press("tab", "down", "down", "slash")
        await pilot.pause()
        opened = type(app.focused), box.display, shown_keys(app)
        await pilot.press("a")
        await pilot.pause()
        after_a = rows(table), table.selected_id, table.filter_text
        await pilot.press("2")
        await pilot.pause()
        after_a2 = rows(table), table.selected_id, table.filter_text
        await pilot.press("escape")
        await pilot.pause()
        cleared = rows(table), table.selected_id, table.filter_text
        closed = type(app.focused), box.display, "escape" in shown_keys(app)

    assert at_start == (False, False)
    assert opened == (FilterBox, True, {"escape": "Clear", "enter": "Done"})
    assert after_a == ([a1, a2], a2, "a")
    assert after_a2 == ([a2], a2, "a2")
    assert cleared == ([a1, a2, b1], a2, "")
    assert closed == (SessionsPane, False, False)


async def test_enter_keeps_the_filter_and_escape_on_the_pane_clears_it(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'enter' key keeps the filter and goes back to the pane. 'escape' there clears it."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        box = app.query_one("#sessions-filter", FilterBox)
        await pilot.press("tab", "slash", "b", "enter")
        await pilot.pause()
        kept = rows(table), table.selected_id, box.display, box.value
        focused = type(app.focused)
        keys = shown_keys(app)
        await pilot.press("escape")
        await pilot.pause()
        cleared = rows(table), table.selected_id, box.display, table.filter_text
        keys_after = shown_keys(app)

    assert kept == ([b1], b1, True, "b")
    assert focused is SessionsPane
    assert keys["escape"] == "Clear filter"
    assert keys["slash"] == "Filter"
    assert cleared == ([a1, a2, b1], b1, False, "")
    assert "escape" not in keys_after


async def test_slash_on_the_projects_pane_narrows_the_projects_by_path(
    fake: FakeClaude, settings: Settings
) -> None:
    """The '/' key on the projects pane narrows the projects by path."""
    _a1, _a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        box = app.query_one("#projects-filter", FilterBox)
        await pilot.press("slash", "B", "enter")
        await pilot.pause()
        narrowed = [str(option.prompt) for option in pane.options]
        focused = type(app.focused)
        await pilot.press("down")
        await pilot.pause()
        chosen = pane.selected_path, rows(app.query_one(SessionsPane))
        await pilot.press("escape")
        await pilot.pause()
        restored = [str(option.prompt) for option in pane.options]
        after = pane.selected_path, pane.highlighted, box.display

    assert narrowed == [ALL_PROJECTS, "/p/b"]
    assert focused is ProjectsPane
    assert chosen == ("/p/b", [b1])
    assert restored == [ALL_PROJECTS, "/p/a", "/p/b"]
    assert after == ("/p/b", 2, False)


async def test_a_filter_that_hides_the_cursor_session_moves_the_cursor_to_its_row(
    fake: FakeClaude, settings: Settings
) -> None:
    """A filter that hides the cursor's session moves the cursor to the row in its place."""
    a1, _a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "slash", "b")
        await pilot.pause()
        narrowed = rows(table), table.selected_id, table.cursor_row
        await pilot.press("escape")
        await pilot.pause()
        restored = rows(table), table.selected_id, table.cursor_row

    assert narrowed == ([b1], b1, 0)
    assert restored == ([a1, _a2, b1], b1, 2)


def trashed(settings: Settings) -> list[str]:
    """The session ids in the Trash, in any order."""
    return sorted(entry.session_id for entry in SessionStore(settings).list_trash())


def toasts(app: ConclaudeApp) -> list[tuple[str, str, str]]:
    """The notifications on show: severity, title and message."""
    return [(n.severity, n.title, n.message) for n in app._notifications]


async def test_d_moves_the_session_under_the_cursor_to_the_trash_with_no_reload(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'd' key moves the session under the cursor to the Trash. Its row goes. No reload."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab")
        await pilot.pause()
        keys = shown_keys(app)
        enabled = app.active_bindings["d"].enabled
        # A session that lands on the disk now shows up only after a reload
        late = new_id()
        fake.transcript("/p/a", late, session_records(late, "/p/a"), mtime=4000)
        await pilot.press("d")
        await pilot.pause()
        after = rows(table), table.selected_id, table.cursor_row
        text = app.query_one(DetailsPane).text
        focused = type(app.focused)
        shown = toasts(app)

    assert (keys["d"], enabled) == ("Delete", True)
    assert after == ([a2, b1], a2, 0)
    assert f"Id:          {a2}" in text
    assert focused is SessionsPane
    assert shown == []
    assert trashed(settings) == [a1]


async def test_repeated_d_walks_down_the_list_and_the_last_row_hands_over_upward(
    fake: FakeClaude, settings: Settings
) -> None:
    """Repeated d walks down the list. The last row hands the cursor to the one above."""
    a1, a2, a3 = new_id(), new_id(), new_id()
    for sid, mtime in ((a1, 3000), (a2, 2000), (a3, 1000)):
        fake.transcript("/p/a", sid, session_records(sid, "/p/a"), mtime=mtime)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("down", "tab", "down")
        await pilot.pause()
        seen = [(rows(table), table.selected_id, table.cursor_row)]
        for _ in range(2):
            await pilot.press("d")
            await pilot.pause()
            seen.append((rows(table), table.selected_id, table.cursor_row))

    assert seen == [
        ([a1, a2, a3], a2, 1),
        ([a1, a3], a3, 1),
        ([a1], a1, 0),
    ]
    assert trashed(settings) == sorted([a2, a3])


async def test_d_has_no_effect_while_another_pane_has_the_focus(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'd' key has no effect while another pane has the focus, and is not listed there."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        seen = []
        for tabs in (0, 2):
            await pilot.press(*(["tab"] * tabs))
            await pilot.pause()
            listed = "d" in shown_keys(app)
            await pilot.press("d")
            await pilot.pause()
            seen.append((type(app.focused), listed, rows(table)))
            await pilot.press(*(["shift+tab"] * tabs))

    assert seen == [
        (ProjectsPane, False, [a1, a2, b1]),
        (DetailsPane, False, [a1, a2, b1]),
    ]
    assert trashed(settings) == []


async def test_a_live_session_stays_and_the_reason_shows(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """A live session stays where it is, and the reason shows to the user."""
    running, other = new_id(), new_id()
    fake.transcript(
        "/p/x",
        running,
        session_records(running, "/p/x", custom_title="Run"),
        mtime=2000,
    )
    fake.marker(100, running, 5000, name="dev:app")
    proc.stat(100, 5000)
    fake.transcript("/p/x", other, session_records(other, "/p/x"), mtime=1000)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "d")
        await pilot.pause()
        after = rows(table), table.selected_id, table.cursor_row
        shown = toasts(app)

    assert after == ([running, other], running, 0)
    assert shown == [
        (
            "error",
            "Not trashed",
            f"session {running[:8]} is live (pid 100) and cannot be trashed",
        )
    ]
    assert trashed(settings) == []


async def test_the_last_session_of_a_project_takes_the_project_with_it(
    fake: FakeClaude, settings: Settings
) -> None:
    """The last session of a project takes the project with it. The cursor moves on."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        table = app.query_one(SessionsPane)
        await pilot.press("down", "down", "tab")
        await pilot.pause()
        before = pane.selected_path, rows(table)
        await pilot.press("d")
        await pilot.pause()
        prompts = [str(option.prompt) for option in pane.options]
        after = pane.selected_path, rows(table), table.selected_id, table.cursor_row
        focused = type(app.focused)
        text = app.query_one(DetailsPane).text

    assert before == ("/p/b", [b1])
    assert prompts == [ALL_PROJECTS, "/p/a"]
    assert after == ("/p/a", [a1, a2], a1, 0)
    assert focused is SessionsPane
    assert f"Id:          {a1}" in text
    assert trashed(settings) == [b1]


async def test_in_all_projects_a_gone_project_leaves_the_cursor_where_it_is(
    fake: FakeClaude, settings: Settings
) -> None:
    """In 'All projects' a gone project leaves the cursor on the row that replaced it."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "down", "down", "d")
        await pilot.pause()
        prompts = [str(option.prompt) for option in pane.options]
        after = pane.selected_path, rows(table), table.selected_id, table.cursor_row

    assert prompts == [ALL_PROJECTS, "/p/a"]
    assert after == (None, [a1, a2], a2, 1)
    assert trashed(settings) == [b1]


async def test_with_no_row_d_is_dimmed_and_does_nothing(
    fake: FakeClaude, settings: Settings
) -> None:
    """With no row on view, d is dimmed in the footer and does nothing."""
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        active = app.active_bindings["d"]
        dimmed = active.binding.show, active.enabled
        await pilot.press("d")
        await pilot.pause()
        shown = toasts(app)

    assert dimmed == (True, False)
    assert shown == []
    assert trashed(settings) == []


def days(app: ConclaudeApp) -> list[str]:
    """The lines of the days pane, top to bottom."""
    return [str(option.prompt) for option in app.screen.query_one(DaysPane).options]


def prompts(app: ConclaudeApp) -> list[str]:
    """The lines of the projects pane, top to bottom."""
    return [str(option.prompt) for option in app.screen.query_one(ProjectsPane).options]


def cursor(table: DataTable) -> tuple[list[str], str | None, int]:
    """The rows, the selected key and the cursor row, in one tuple."""
    return rows(table), table.selected_id, table.cursor_row


def two_days_of_trash(
    fake: FakeClaude, settings: Settings
) -> tuple[TrashEntry, TrashEntry, TrashEntry]:
    """The three sessions, trashed: A1 then A2 on one day, B1 the day before."""
    a1, a2, b1 = three_sessions(fake)
    store = SessionStore(settings)
    later = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
    e_a1 = trash_session(settings, store.find_session(a1), now=later)
    e_a2 = trash_session(
        settings, store.find_session(a2), now=later - timedelta(minutes=5)
    )
    e_b1 = trash_session(
        settings, store.find_session(b1), now=later - timedelta(days=1)
    )
    return e_a1, e_a2, e_b1


async def test_t_switches_the_panes_to_the_trash_and_back_again(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 't' key switches the panes to the Trash. 't' again brings the sessions back as before."""
    a1, a2, b1 = three_sessions(fake)
    entry = SessionStore(settings).trash(b1)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("tab", "down")
        await pilot.pause()
        before = type(app.screen), type(app.focused), shown_keys(app)["t"]
        await pilot.press("t")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        in_trash = (
            type(app.screen),
            type(app.focused),
            shown_keys(app)["t"],
            days(app),
            cursor(table),
            columns(table),
        )
        header = app.screen.query_one(TitleBar).region
        left = app.screen.query_one(DaysPane).region
        upper = table.region
        lower = app.screen.query_one(EntryPane).region
        await pilot.press("t")
        await pilot.pause()
        sessions = app.screen.query_one(SessionsPane)
        after = type(app.screen), type(app.focused), cursor(sessions)

    assert before == (MainScreen, SessionsPane, "Trash (1)")
    assert in_trash == (
        TrashScreen,
        EntriesPane,
        "Sessions",
        [ALL_DAYS, fmt.day(entry.trashed_at)],
        ([entry.id], entry.id, 0),
        ["Title", "Trashed", "Size", "Project"],
    )
    assert (header.y, header.height) == (0, 1)
    assert left.x == 0
    assert left.right == upper.x == lower.x
    assert left.y == upper.y == header.bottom
    assert upper.bottom == lower.y
    assert after == (MainScreen, SessionsPane, ([a1, a2], a2, 1))


async def test_the_trash_lists_its_entries_newest_first_grouped_by_day(
    fake: FakeClaude, settings: Settings
) -> None:
    """The Trash lists its entries newest first. A day on the left narrows them to it."""
    e_a1, e_a2, e_b1 = two_days_of_trash(fake, settings)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        pane = app.screen.query_one(DaysPane)
        listed = days(app), rows(table), pane.selected_day
        cells = [
            str(table.get_cell(e_a1.id, key))
            for key in ("title", "trashed_at", "size", "project")
        ]
        await pilot.press("shift+tab", "down")
        await pilot.pause()
        later = type(app.focused), pane.selected_day, rows(table)
        await pilot.press("down")
        await pilot.pause()
        earlier = pane.selected_day, rows(table)
        await pilot.press("enter")
        await pilot.pause()
        entered = type(app.focused)

    day_later, day_earlier = fmt.day(e_a1.trashed_at), fmt.day(e_b1.trashed_at)
    assert day_later != day_earlier
    assert fmt.day(e_a2.trashed_at) == day_later
    assert listed == (
        [ALL_DAYS, day_later, day_earlier],
        [e_a1.id, e_a2.id, e_b1.id],
        None,
    )
    assert cells == ["A1", fmt.timestamp(e_a1.trashed_at), fmt.size(e_a1.size), "/p/a"]
    assert later == (DaysPane, day_later, [e_a1.id, e_a2.id])
    assert earlier == (day_earlier, [e_b1.id])
    assert entered is EntriesPane


async def test_the_entry_pane_shows_the_entry_under_the_cursor_with_every_part(
    fake: FakeClaude, settings: Settings
) -> None:
    """The entry pane shows the entry under the cursor: the session, when, the size, the parts."""
    sid, other = new_id(), new_id()
    parts = fake.every_part("/p/x", sid)
    fake.transcript("/p/x", other)
    store = SessionStore(settings)
    later = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
    entry = trash_session(
        settings, store.find_session(sid), reason="pressed d", now=later
    )
    trash_session(settings, store.find_session(other), now=later - timedelta(hours=1))
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        pane = app.screen.query_one(EntryPane)
        first = pane.text
        painted = str(app.screen.query_one("#entry-text", Static).render())
        expected = painted_lines(pane, fmt.describe_entry(entry))
        await pilot.press("down")
        await pilot.pause()
        second = pane.text

    assert painted == first
    assert first.splitlines() == expected
    assert re.search(rf"^Session: +{sid}$", first, re.M)
    assert re.search(rf"^Trashed: +{re.escape(fmt.timestamp(later))}$", first, re.M)
    assert re.search(r"^Reason: +pressed d$", first, re.M)
    assert re.search(rf"^Size: +{re.escape(fmt.size(entry.size))}$", first, re.M)
    for kind in ("transcript", "sidecar", "session-env", "file-history", "todo"):
        # A long path is cut in the middle, so the line always ends with the name.
        # A name that fills the room on its own leaves no room for the size.
        name = re.escape(parts[kind].name)
        line = rf"^{kind.capitalize()}: +(\S+  )?\S*/{name}$"
        assert re.search(line, first, re.M), kind
    assert re.search(rf"^Session: +{other}$", second, re.M)
    assert sid not in second


async def test_u_puts_the_entry_back_and_the_session_is_listed_again_with_no_reload(
    fake: FakeClaude, settings: Settings
) -> None:
    """U puts the entry back. Its row goes. Back with the sessions, the session is listed."""
    a1, a2, b1 = three_sessions(fake)
    entry = SessionStore(settings).trash(b1)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        before = prompts(app)
        await pilot.press("t")
        await pilot.pause()
        keys = shown_keys(app)
        await pilot.press("u")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        emptied = cursor(table), days(app), app.screen.query_one(EntryPane).text
        shown = toasts(app)
        # A session that lands on the disk now shows up only after a reload
        late = new_id()
        fake.transcript("/p/a", late, session_records(late, "/p/a"), mtime=4000)
        await pilot.press("t")
        await pilot.pause()
        after = prompts(app), cursor(app.screen.query_one(SessionsPane))
        text = app.screen.query_one(DetailsPane).text

    assert before == [ALL_PROJECTS, "/p/a"]
    assert (keys["u"], keys["x"]) == ("Restore", "Purge")
    assert emptied == (([], None, 0), [ALL_DAYS], "No entry.")
    assert shown == []
    assert not entry.path.exists()
    assert trashed(settings) == []
    assert after == ([ALL_PROJECTS, "/p/a", "/p/b"], ([a1, a2, b1], a1, 0))
    assert f"Id:          {a1}" in text


async def test_a_restore_blocked_by_an_occupied_path_reports_the_clash_and_changes_nothing(
    fake: FakeClaude, settings: Settings
) -> None:
    """A restore blocked by something in its way reports the clash and changes nothing."""
    a1, a2, b1 = three_sessions(fake)
    entry = SessionStore(settings).trash(a1)
    # Something new sits where the transcript must go back
    in_the_way = fake.transcript(
        "/p/a", a1, session_records(a1, "/p/a", custom_title="New"), mtime=3000
    )
    before = snapshot(settings.claude_dir), snapshot(settings.trash_dir)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t", "u")
        await pilot.pause()
        after = type(app.screen), cursor(app.screen.query_one(EntriesPane))
        shown = toasts(app)
        await pilot.press("t")
        await pilot.pause()
        listed = rows(app.screen.query_one(SessionsPane))

    assert after == (TrashScreen, ([entry.id], entry.id, 0))
    assert shown == [
        (
            "error",
            "Not restored",
            f"cannot restore {entry.id}: {in_the_way} is in the way",
        )
    ]
    assert (snapshot(settings.claude_dir), snapshot(settings.trash_dir)) == before
    assert listed == [a1, a2, b1]


async def test_x_removes_the_entry_for_good(
    fake: FakeClaude, settings: Settings
) -> None:
    """X removes the entry from the disk for good. The session does not come back."""
    a1, a2, b1 = three_sessions(fake)
    entry = SessionStore(settings).trash(a1)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t", "x")
        await pilot.pause()
        emptied = cursor(app.screen.query_one(EntriesPane)), days(app), toasts(app)
        await pilot.press("t")
        await pilot.pause()
        listed = rows(app.screen.query_one(SessionsPane))

    assert emptied == (([], None, 0), [ALL_DAYS], [])
    assert not entry.path.exists()
    assert trashed(settings) == []
    assert listed == [a2, b1]
    assert {s.id for s in SessionStore(settings).list_sessions()} == {a2, b1}


def titles(app: ConclaudeApp) -> tuple[str, str, str, str]:
    """The view in the title bar, the label of the 't' key, the left pane title, the table title."""
    screen = app.screen
    return (
        screen.query_one(TitleBar).view,
        shown_keys(app)["t"],
        str(screen.query_one(Lister).border_title),
        str(screen.query_one(Table).border_title),
    )


async def test_the_title_bar_names_the_view_on_the_left_and_the_tool_on_the_right(
    fake: FakeClaude, settings: Settings
) -> None:
    """The title bar names the view at the left edge, and the tool with its version at the right."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        bar = app.screen.query_one(TitleBar).region
        view = app.screen.query_one("#view").region
        brand = app.screen.query_one("#brand").region
        top = app.screen._compositor.render_strips()[0].text
        await pilot.press("t")
        await pilot.pause()
        in_trash = app.screen._compositor.render_strips()[0].text

    assert (bar.x, bar.y, bar.width, bar.height) == (0, 0, WIDE[0], 1)
    assert view.x == 0
    assert brand.right == WIDE[0]
    assert top.startswith(" Sessions ")
    assert top.rstrip().endswith(f" {__title__} v{__version__}")
    assert in_trash.startswith(" Trash ")
    assert in_trash.rstrip().endswith(f" {__title__} v{__version__}")


async def test_the_t_key_and_the_pane_titles_say_what_they_hold_after_every_change(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 't' key carries the Trash count, each pane title what it shows. All follow a change."""
    a1, a2, b1 = three_sessions(fake)
    store = SessionStore(settings)
    a1_size = store.find_session(a1).size
    a2_size = store.find_session(a2).size
    long_ago = datetime(2020, 1, 1, tzinfo=timezone.utc)
    old = trash_session(settings, store.find_session(b1), now=long_ago)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        at_start = titles(app)
        await pilot.press("tab", "d")
        await pilot.pause()
        after_delete = titles(app)
        await pilot.press("t")
        await pilot.pause()
        in_trash = titles(app)
        await pilot.press("u")
        await pilot.pause()
        after_restore = titles(app)
        await pilot.press("x")
        await pilot.pause()
        after_purge = titles(app)
        await pilot.press("t")
        await pilot.pause()
        back = titles(app)

    both = f"Sessions (2 sessions, {fmt.size(a1_size + a2_size)} total)"
    one_left = f"Sessions (1 session, {fmt.size(a2_size)} total)"
    one = f"Trash (1 entry, {fmt.size(old.size)} total)"
    two = f"Trash (2 entries, {fmt.size(old.size + a1_size)} total)"
    assert at_start == ("Sessions", "Trash (1)", "Projects (1)", both)
    assert after_delete == ("Sessions", "Trash (2)", "Projects (1)", one_left)
    assert in_trash == ("Trash", "Sessions", "Days (2)", two)
    assert after_restore == ("Trash", "Sessions", "Days (1)", one)
    assert after_purge == ("Trash", "Sessions", "Days (empty)", "Trash (empty)")
    assert back == ("Sessions", "Trash", "Projects (1)", both)


async def test_the_pane_titles_follow_the_project_in_view_and_the_filter(
    fake: FakeClaude, settings: Settings
) -> None:
    """The pane titles count what is on view: one project's sessions, or the filtered rows."""
    a1, a2, b1 = three_sessions(fake)
    store = SessionStore(settings)
    size = {s: store.find_session(s).size for s in (a1, a2, b1)}
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        all_projects = titles(app)[2:]
        await pilot.press("down", "down")
        await pilot.pause()
        one_project = titles(app)[2:]
        await pilot.press("slash", "a", "enter")
        await pilot.pause()
        projects_narrowed = titles(app)[2:]
        # Tab would land on the filter box the projects pane now shows.
        app.screen.query_one(SessionsPane).focus()
        await pilot.pause()
        await pilot.press("slash", "1", "enter")
        await pilot.pause()
        sessions_narrowed = titles(app)[2:]

    assert all_projects == (
        "Projects (2)",
        f"Sessions (3 sessions, {fmt.size(sum(size.values()))} total)",
    )
    assert one_project == (
        "Projects (2)",
        f"Sessions (1 session, {fmt.size(size[b1])} total)",
    )
    assert projects_narrowed == (
        "Projects (1)",
        f"Sessions (2 sessions, {fmt.size(size[a1] + size[a2])} total)",
    )
    assert sessions_narrowed == (
        "Projects (1)",
        f"Sessions (1 session, {fmt.size(size[a1])} total)",
    )


async def test_restore_and_purge_do_nothing_outside_the_trash_table(
    fake: FakeClaude, settings: Settings
) -> None:
    """U and x are not listed and do nothing outside the Trash table."""
    a1, a2, b1 = three_sessions(fake)
    entry = SessionStore(settings).trash(b1)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        seen = []
        for _ in range(3):
            listed = {"u", "x"} & set(shown_keys(app))
            await pilot.press("u", "x")
            await pilot.pause()
            seen.append(
                (type(app.focused), listed, rows(app.screen.query_one(SessionsPane)))
            )
            await pilot.press("tab")
        await pilot.press("t")
        await pilot.pause()
        for _ in range(2):
            await pilot.press("tab")
            await pilot.pause()
            listed = {"u", "x"} & set(shown_keys(app))
            await pilot.press("u", "x")
            await pilot.pause()
            seen.append(
                (type(app.focused), listed, rows(app.screen.query_one(EntriesPane)))
            )
        shown = toasts(app)

    assert seen == [
        (ProjectsPane, set(), [a1, a2]),
        (SessionsPane, set(), [a1, a2]),
        (DetailsPane, set(), [a1, a2]),
        (EntryPane, set(), [entry.id]),
        (DaysPane, set(), [entry.id]),
    ]
    assert shown == []
    assert trashed(settings) == [b1]


async def test_with_an_empty_trash_the_panes_are_empty_and_the_keys_are_dimmed(
    fake: FakeClaude, settings: Settings
) -> None:
    """With an empty Trash the panes are empty, u and x are dimmed and do nothing."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        empty = (
            days(app),
            cursor(table),
            app.screen.query_one(EntryPane).text,
            app.screen.query_one(TitleBar).view,
        )
        dimmed = [
            (app.active_bindings[key].binding.show, app.active_bindings[key].enabled)
            for key in ("u", "x")
        ]
        await pilot.press("u", "x")
        await pilot.pause()
        shown = toasts(app)
        await pilot.press("t")
        await pilot.pause()
        back = type(app.screen)

    assert empty == ([ALL_DAYS], ([], None, 0), "No entry.", "Trash")
    assert dimmed == [(True, False), (True, False)]
    assert shown == []
    assert back is MainScreen


async def test_the_last_entry_of_a_day_takes_the_day_with_it(
    fake: FakeClaude, settings: Settings
) -> None:
    """The last entry of a day takes the day with it. The cursor moves on to the next day."""
    e_a1, e_a2, e_b1 = two_days_of_trash(fake, settings)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        pane = app.screen.query_one(DaysPane)
        table = app.screen.query_one(EntriesPane)
        await pilot.press("shift+tab", "down", "down", "tab")
        await pilot.pause()
        before = pane.selected_day, rows(table)
        await pilot.press("x")
        await pilot.pause()
        after = days(app), pane.selected_day, cursor(table), type(app.focused)
        text = app.screen.query_one(EntryPane).text

    day_later = fmt.day(e_a1.trashed_at)
    assert before == (fmt.day(e_b1.trashed_at), [e_b1.id])
    assert after == (
        [ALL_DAYS, day_later],
        day_later,
        ([e_a1.id, e_a2.id], e_a1.id, 0),
        EntriesPane,
    )
    assert e_a1.session_id in text
    assert trashed(settings) == sorted([e_a1.session_id, e_a2.session_id])


async def test_repeated_u_walks_down_the_entries_and_every_session_put_back_is_listed(
    fake: FakeClaude, settings: Settings
) -> None:
    """Repeated u walks down the entries. Every session put back is listed on return."""
    e_a1, e_a2, e_b1 = two_days_of_trash(fake, settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        at_start = prompts(app)
        await pilot.press("t", "down")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        seen = [cursor(table)]
        for _ in range(2):
            await pilot.press("u")
            await pilot.pause()
            seen.append(cursor(table))
        await pilot.press("t")
        await pilot.pause()
        back = prompts(app), cursor(app.screen.query_one(SessionsPane))

    a1, a2, b1 = e_a1.session_id, e_a2.session_id, e_b1.session_id
    assert at_start == [ALL_PROJECTS]
    assert seen == [
        ([e_a1.id, e_a2.id, e_b1.id], e_a2.id, 1),
        ([e_a1.id, e_b1.id], e_b1.id, 1),
        ([e_a1.id], e_a1.id, 0),
    ]
    assert back == ([ALL_PROJECTS, "/p/a", "/p/b"], ([a2, b1], a2, 0))
    assert trashed(settings) == [a1]


async def test_slash_narrows_the_entries_by_title(
    fake: FakeClaude, settings: Settings
) -> None:
    """Slash narrows the entries by title, case aside. Escape brings them all back."""
    e_a1, e_a2, e_b1 = two_days_of_trash(fake, settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t", "slash", "b")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        narrowed = type(app.focused), cursor(table), table.filter_text
        await pilot.press("escape")
        await pilot.pause()
        cleared = type(app.focused), rows(table), table.filter_text

    assert narrowed == (FilterBox, ([e_b1.id], e_b1.id, 0), "b")
    assert cleared == (EntriesPane, [e_a1.id, e_a2.id, e_b1.id], "")


async def test_r_in_trash_mode_reads_the_trash_again_and_the_cursor_keeps_its_entry(
    fake: FakeClaude, settings: Settings
) -> None:
    """R in Trash mode reads the Trash again. The cursor keeps its entry by id."""
    a1, a2, _b1 = three_sessions(fake)
    store = SessionStore(settings)
    noon = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
    first = trash_session(settings, store.find_session(a2), now=noon)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        before = cursor(table)
        second = trash_session(
            settings, store.find_session(a1), now=noon + timedelta(minutes=1)
        )
        await pilot.press("r")
        await pilot.pause()
        after = cursor(table), str(table.border_title)

    assert before == ([first.id], first.id, 0)
    assert after == (
        ([second.id, first.id], first.id, 1),
        f"Trash (2 entries, {fmt.size(first.size + second.size)} total)",
    )


LONG = "/home/u/dev/projects/some-long-folder-name"


def long_paths(fake: FakeClaude, count: int) -> list[tuple[str, str]]:
    """``count`` projects with long paths that differ in their last part alone.

    One session each, newest first. Each pair is the path and the session id.
    """
    projects = []
    for number in range(count):
        path, sid = f"{LONG}/app-{number:02d}", new_id()
        records = session_records(sid, path, custom_title=f"T{number}")
        fake.transcript(path, sid, records, mtime=9000 - number)
        projects.append((path, sid))
    return projects


def column_width(table: DataTable, key: str) -> int:
    """The columns the cells of one column have for their text."""
    return next(c.width for c in table.columns.values() if c.key.value == key)


async def test_a_long_project_path_is_cut_in_the_middle_and_keeps_its_end(
    fake: FakeClaude, settings: Settings
) -> None:
    """A long project path is cut in the middle, at the slashes, and keeps its end.

    Two paths that differ in their last part alone stay apart. The id of the
    line is still the whole path.
    """
    [(one, _a), (two, _b)] = long_paths(fake, 2)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        room = pane.scrollable_content_region.width
        shown = prompts(app)
        ids = [option.id for option in pane.options]
        await pilot.press("down")
        await pilot.pause()
        chosen = pane.selected_path

    assert 0 < room < len(one)
    assert shown == [ALL_PROJECTS, fmt.path(one, room), fmt.path(two, room)]
    assert shown[1].startswith("/home/") and shown[1].endswith("/app-00")
    assert shown[2].endswith("/app-01")
    assert settings.cut_mark in shown[1]
    assert len(shown[1]) <= room
    assert ids == [None, one, two]
    assert chosen == one


async def test_the_paths_follow_the_width_of_the_projects_pane(
    fake: FakeClaude, settings: Settings
) -> None:
    """The paths are written again when the pane gets wider. The highlight stays."""
    [(one, _a), (two, b)] = long_paths(fake, 2)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        await pilot.press("down", "down")
        await pilot.pause()
        narrow = pane.scrollable_content_region.width, prompts(app)
        await pilot.resize_terminal(220, WIDE[1])
        await pilot.pause()
        wide = pane.scrollable_content_region.width, prompts(app)
        after = pane.selected_path, pane.highlighted, rows(app.query_one(SessionsPane))

    assert narrow[0] < wide[0]
    assert narrow[1] == [
        ALL_PROJECTS,
        fmt.path(one, narrow[0]),
        fmt.path(two, narrow[0]),
    ]
    assert wide[1] == [ALL_PROJECTS, one, two]
    assert after == (two, 2, [b])


async def test_a_scrollbar_takes_its_columns_from_the_paths(
    fake: FakeClaude, settings: Settings
) -> None:
    """When the list needs a scrollbar, the paths leave it its columns."""
    projects = long_paths(fake, 30)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=(WIDE[0], 20)) as pilot:
        await pilot.pause()
        pane = app.query_one(ProjectsPane)
        scrollbar = pane.show_vertical_scrollbar
        room = pane.scrollable_content_region.width
        narrower = room < pane.content_region.width
        shown = prompts(app)[1:]

    assert scrollbar and narrower
    assert shown == [fmt.path(path, room) for path, _ in projects]
    assert all(len(line) <= room for line in shown)


async def test_the_project_column_cuts_a_long_path_in_the_middle_too(
    fake: FakeClaude, settings: Settings
) -> None:
    """The Project column of the sessions table cuts a long path the same way."""
    [(one, a), (two, b)] = long_paths(fake, 2)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        width = column_width(table, "project")
        cells = [str(table.get_cell(sid, "project")) for sid in (a, b)]

    assert 0 < width < len(one)
    assert cells == [fmt.path(one, width), fmt.path(two, width)]
    assert cells[0].endswith("/app-00") and cells[1].endswith("/app-01")
    assert settings.cut_mark in cells[0]


async def test_the_trash_table_cuts_a_long_project_path_in_the_middle_too(
    fake: FakeClaude, settings: Settings
) -> None:
    """The Project column of the Trash table cuts a long path the same way."""
    [(one, a)] = long_paths(fake, 1)
    entry = SessionStore(settings).trash(a)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        width = column_width(table, "project")
        cell = str(table.get_cell(entry.id, "project"))

    assert 0 < width < len(one)
    assert cell == fmt.path(one, width)
    assert cell.endswith("/app-00") and settings.cut_mark in cell


TALE = (
    "This session is being continued from a previous conversation "
    "that ran out of context"
)


async def test_a_long_title_is_cut_in_the_middle_and_keeps_its_end(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """A long title is cut in the middle, by the character, and its end stays.

    The state marks take no room from the title: they have a column of their own.
    """
    one, two = new_id(), new_id()
    fake.transcript(
        "/p/a",
        one,
        session_records(one, "/p/a", custom_title=f"{TALE}, part one"),
        mtime=3000,
    )
    fake.transcript(
        "/p/a",
        two,
        session_records(two, "/p/a", custom_title=f"{TALE}, part two"),
        mtime=2000,
    )
    fake.marker(100, two, 5000, name=f"{TALE}, part two")
    proc.stat(100, 5000)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        width = column_width(table, "title")
        cells = [str(table.get_cell(sid, "title")) for sid in (one, two)]
        marks = str(table.get_cell(two, "state"))

    assert 0 < width < len(TALE)
    assert cells == [
        fmt.title(f"{TALE}, part one", width),
        fmt.title(f"{TALE}, part two", width),
    ]
    assert cells[0].endswith("part one") and cells[1].endswith("part two")
    assert settings.cut_mark in cells[0]
    assert marks == "L--"


async def test_the_trash_table_cuts_a_long_title_in_the_middle_too(
    fake: FakeClaude, settings: Settings
) -> None:
    """The Title column of the Trash table cuts a long title the same way."""
    sid = new_id()
    fake.transcript(
        "/p/a", sid, session_records(sid, "/p/a", custom_title=f"{TALE}, part one")
    )
    entry = SessionStore(settings).trash(sid)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.screen.query_one(EntriesPane)
        width = column_width(table, "title")
        cell = str(table.get_cell(entry.id, "title"))

    assert 0 < width < len(TALE)
    assert cell == fmt.title(entry.title, width)
    assert cell.endswith("part one") and settings.cut_mark in cell


async def test_the_about_box_names_the_tool_its_version_and_its_address(
    fake: FakeClaude, settings: Settings
) -> None:
    """The ? key opens the About box. Escape closes it and the pane has the focus back."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        before = type(app.screen), type(app.focused)
        await pilot.press("question_mark")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AboutScreen)
        lines = screen.text.splitlines()
        shown = str(screen.query_one("#about-text", Static).content)
        await pilot.press("escape")
        await pilot.pause()
        after = type(app.screen), type(app.focused)

    assert before == (MainScreen, ProjectsPane)
    assert lines[:3] == [
        f"{__title__} {__version__}",
        __description__,
        f"Copyright © 2026 {__author__}",
    ]
    assert lines[-1] == __url__
    assert shown == screen.text
    assert after == (MainScreen, ProjectsPane)


async def test_the_about_box_holds_a_qr_code_of_the_address(
    fake: FakeClaude, settings: Settings
) -> None:
    """The box holds the address as a QR code too, to point a phone at."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AboutScreen)
        text = screen.text

    code = render_qr(__url__, error=QR_ERROR, border=QR_BORDER)
    lines = code.splitlines()
    assert f"{code}\n{__url__}" in text
    # Every line of a QR code is as wide as the code, and the three corners
    # a reader looks for sit in it.
    assert len({len(line) for line in lines}) == 1
    assert len(lines) == 17
    corner = "█▀▀▀▀▀█"
    assert lines[1].strip().startswith(corner) and lines[1].strip().endswith(corner)
    assert lines[-5].strip().startswith(corner)


async def test_the_about_box_fits_a_small_window_and_scrolls_in_a_smaller_one(
    fake: FakeClaude, settings: Settings
) -> None:
    """The box fits an 80x24 window whole. A window under that scrolls it."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        box = app.screen.query_one("#about", VerticalScroll)
        region = box.region
        whole = box.max_scroll_x == 0 and box.max_scroll_y == 0
        focused = app.focused

        await pilot.resize_terminal(60, 18)
        await pilot.pause()
        hidden = box.max_scroll_y
        await pilot.press("down", "down")
        await pilot.pause()
        scrolled = box.scroll_y

    assert region.width <= 80 and region.height <= 24
    assert whole, "the box did not fit an 80x24 window"
    assert focused is box
    assert hidden > 0
    assert scrolled == 2


async def test_every_key_of_the_about_box_closes_it_and_q_does_not_quit(
    fake: FakeClaude, settings: Settings
) -> None:
    """'escape', 'enter', '?' and 'q' all close the box. In the box, 'q' closes it and stays."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    closed: list[type] = []
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        for key in ("escape", "enter", "question_mark", "q"):
            await pilot.press("question_mark")
            await pilot.pause()
            assert type(app.screen) is AboutScreen, f"{key} did not open the box"
            await pilot.press(key)
            await pilot.pause()
            closed.append(type(app.screen))
        running = app.is_running

    assert closed == [MainScreen] * 4
    assert running is True


async def test_the_about_key_works_on_every_pane_and_in_the_trash(
    fake: FakeClaude, settings: Settings
) -> None:
    """Every pane lists the About key and opens the box with it, Trash mode too."""
    _a1, _a2, b1 = three_sessions(fake)
    SessionStore(settings).trash(b1)
    app = ConclaudeApp(settings)
    opened: list[tuple[type, type]] = []
    listed: list[str] = []
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        for keys in ((), ("tab",), ("tab", "tab"), ("t",)):
            await pilot.press(*keys)
            await pilot.pause()
            pane, under = type(app.focused), type(app.screen)
            listed.append(shown_keys(app)["question_mark"])
            await pilot.press("question_mark")
            await pilot.pause()
            opened.append((type(app.screen), under))
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.focused) is pane, f"focus lost from {pane.__name__}"

    assert opened == [
        (AboutScreen, MainScreen),
        (AboutScreen, MainScreen),
        (AboutScreen, MainScreen),
        (AboutScreen, TrashScreen),
    ]
    assert listed == ["About"] * 4


async def test_a_long_line_in_the_details_pane_is_cut_in_the_middle_and_never_wraps(
    fake: FakeClaude, settings: Settings
) -> None:
    """A long line in the details pane is cut in the middle, at the slashes. It never wraps.

    The end of a path stays, so the folder or the file name is always on view.
    A wider window brings the whole line back.
    """
    sid = new_id()
    fake.transcript(LONG, sid, session_records(sid, LONG, custom_title="Hello"))
    fake.sidecar(LONG, sid, agents=3)
    details = SessionStore(settings).details(sid)
    folder = str(details.session.transcript_path.parent)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=(110, 24)) as pilot:
        await pilot.pause()
        pane = app.query_one(DetailsPane)
        static = app.query_one("#details-text", Static)
        narrow = pane.text.splitlines()
        expected = painted_lines(pane, fmt.describe(details))
        room = pane.scrollable_content_region.width
        height = static.region.height
        scrollbar = pane.show_vertical_scrollbar
        await pilot.resize_terminal(220, 60)
        await pilot.pause()
        wide = pane.text.splitlines()

    shown = next(line for line in narrow if line.startswith("Folder:"))
    assert scrollbar and len(folder) > room
    assert narrow == expected
    assert all(len(line) <= room for line in narrow)
    assert height == len(narrow) == len(wide)
    assert settings.cut_mark in shown
    assert shown.endswith("/" + folder.rsplit("/", 1)[1])
    assert f"Folder:      {folder}" in wide


def test_the_stylesheet_names_no_literal_colour() -> None:
    """The stylesheet names no literal colour: only theme variables."""
    path = Path(conclaude.tui.app.__file__).with_name(ConclaudeApp.CSS_PATH)
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    values = re.findall(r":\s*([^;{}]+);", text)
    literal = []
    variables = set()
    for value in values:
        for token in value.split():
            if token.startswith("$"):
                variables.add(token)
                continue

            try:
                Color.parse(token)
            except ColorParseError:
                continue
            literal.append(token)

    assert literal == []
    assert {
        "$surface",
        "$border",
        "$border-blurred",
        "$text",
        "$text-muted",
    } <= variables


async def test_the_msgs_column_shows_the_cached_turn_count_and_marks_a_stale_one(
    fake: FakeClaude, settings: Settings
) -> None:
    """Msgs is blank before a scan. After one and a reload it shows the turn count.
    After the transcript grows, the old count stays, a star in front. The Msgs order
    puts the busiest first and the unscanned last, and a click on the header
    turns it round.
    """
    quiet, busy, unscanned = new_id(), new_id(), new_id()
    fake.transcript("/p/x", quiet, session_records(quiet, "/p/x"), mtime=1000)
    busy_records = session_records(busy, "/p/x") + [prompt_record(busy, "More")]
    busy_path = fake.transcript("/p/x", busy, busy_records, mtime=2000)
    fake.transcript("/p/x", unscanned, mtime=3000)
    store = SessionStore(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        before = [str(table.get_cell(sid, "msgs")) for sid in rows(table)]
        for session in store.list_sessions():
            if session.id != unscanned:
                store.scan_of(session)
        await pilot.press("r")
        await pilot.pause()
        after = {sid: str(table.get_cell(sid, "msgs")) for sid in rows(table)}
        with open(busy_path, "ab") as handle:
            handle.write(dump_line(prompt_record(busy, "One more")))
        await pilot.press("r")
        await pilot.pause()
        stale = {sid: str(table.get_cell(sid, "msgs")) for sid in rows(table)}
        await pilot.press("tab", "o", "o")
        await pilot.pause()
        by_msgs = rows(table), table.sorting
        await pilot.press("O")
        await pilot.pause()
        reversed_msgs = rows(table), table.sorting

    assert before == ["", "", ""]
    assert after == {quiet: "1", busy: "2", unscanned: ""}
    assert stale == {quiet: "1", busy: "*2", unscanned: ""}
    assert by_msgs == ([busy, quiet, unscanned], ("msgs", True))
    assert reversed_msgs == ([unscanned, quiet, busy], ("msgs", False))


async def until(check: Callable[[], bool], pilot: Pilot[None]) -> bool:
    """Give the screen its turns until ``check`` holds. Gives up after a second."""
    for _ in range(100):
        await pilot.pause()
        if check():
            return True
        await asyncio.sleep(0.01)
    return False


def gated_scan(
    monkeypatch: pytest.MonkeyPatch, gate: threading.Event, hold: int
) -> list[Path]:
    """Make the deep scan wait on ``gate`` at its ``hold``-th transcript.

    Every transcript it starts lands in the list it gives back, so a test can
    tell how far the scan walked.
    """
    real = conclaude.core.store.deep_scan
    seen: list[Path] = []

    def held(path: Path, now: datetime | None = None) -> Figures:
        """One transcript, read after the gate opens when it is the one held."""
        seen.append(path)
        if len(seen) == hold:
            gate.wait(5)
        return real(path, now)

    monkeypatch.setattr(conclaude.core.store, "deep_scan", held)
    return seen


async def test_s_deep_scans_the_session_under_the_cursor_and_opens_no_screen(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 's' key reads one transcript in full and leaves the panes where they are.

    The Msgs cell of that row fills in, the details pane takes the figures, and
    a notification says what was counted. The figures need no screen of their
    own: the details pane already holds every one of them.
    """
    a1, _a2, _b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab")
        await pilot.pause()
        key = shown_keys(app).get("s")
        blank = str(table.get_cell(a1, "msgs"))
        await pilot.press("s")
        await app.workers.wait_for_complete()
        await pilot.pause()
        where = type(app.screen), type(app.focused)
        cell = str(table.get_cell(a1, "msgs"))
        details = app.query_one(DetailsPane).text
        shown = toasts(app)

    assert key == "Scan"
    assert blank == ""
    assert where == (MainScreen, SessionsPane)
    assert cell == "1"
    assert re.search(r"^Turns: +1$", details, re.M)
    assert re.search(r"^Tool calls: +0$", details, re.M)
    assert shown == [("information", "Deep scan", "1 turn, 0 tokens, 0 tool calls")]


async def test_s_takes_figures_already_in_the_cache_and_reads_no_transcript_again(
    fake: FakeClaude, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result already cached shows at once. Nothing is computed a second time."""
    a1, _a2, _b1 = three_sessions(fake)
    store = SessionStore(settings)
    store.scan_of(store.find_session(a1))
    gate = threading.Event()
    gate.set()
    seen = gated_scan(monkeypatch, gate, hold=0)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("tab", "s")
        await app.workers.wait_for_complete()
        await pilot.pause()
        cell = str(app.query_one(SessionsPane).get_cell(a1, "msgs"))
        details = app.query_one(DetailsPane).text
        shown = toasts(app)

    assert seen == []
    assert cell == "1"
    assert re.search(r"^Turns: +1$", details, re.M)
    assert shown == [("information", "Deep scan", "1 turn, 0 tokens, 0 tool calls")]


async def test_capital_s_scans_every_session_listed_and_fills_the_msgs_column(
    fake: FakeClaude, settings: Settings
) -> None:
    """The 'S' key scans the sessions on view and leaves the others alone.

    Every row on view fills in, and the count of what was done shows at the end.
    """
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("down")
        await pilot.pause()
        listed = rows(table)
        await pilot.press("tab")
        await pilot.pause()
        key = shown_keys(app).get("S")
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        cells = {sid: str(table.get_cell(sid, "msgs")) for sid in rows(table)}
        shown = toasts(app)

    assert key == "Scan all"
    assert listed == [a1, a2]
    assert cells == {a1: "1", a2: "1"}
    assert shown == [
        ("information", "Deep scan", "Reading 2 transcripts"),
        ("information", "Deep scan", "2 scanned, 0 already fresh, 0 failed"),
    ]
    assert {path.stem for path in Cache(settings).get_all()} == {a1, a2}
    assert b1 not in {a1, a2}


async def test_the_screen_answers_keys_while_a_scan_runs_in_the_background(
    fake: FakeClaude, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deep scan holds no key. The cursor still moves while a transcript is read."""
    a1, a2, b1 = three_sessions(fake)
    gate = threading.Event()
    gated_scan(monkeypatch, gate, hold=1)
    app = ConclaudeApp(settings)
    try:
        async with app.run_test(size=WIDE) as pilot:
            await pilot.pause()
            table = app.query_one(SessionsPane)
            await pilot.press("tab", "S")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            during = [str(table.get_cell(sid, "msgs")) for sid in rows(table)]
            moved = table.selected_id
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            after = {sid: str(table.get_cell(sid, "msgs")) for sid in rows(table)}
    finally:
        gate.set()

    assert during == ["", "", ""]
    assert moved == a2
    assert after == {a1: "1", a2: "1", b1: "1"}


async def test_a_scan_cut_short_by_a_quit_leaves_the_cache_whole(
    fake: FakeClaude, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user quits while a scan runs. Every session done by then is in the cache,
    the cache still reads, and the session held mid-read is simply not in it.
    """
    a1, a2, _b1 = three_sessions(fake)
    gate = threading.Event()
    seen = gated_scan(monkeypatch, gate, hold=2)
    app = ConclaudeApp(settings)
    try:
        async with app.run_test(size=WIDE) as pilot:
            await pilot.pause()
            await pilot.press("tab", "S")
            held = await until(lambda: len(seen) == 2, pilot)
            await pilot.press("q")
            await pilot.pause()
        kept = {
            path.stem: found.turns for path, found in Cache(settings).get_all().items()
        }
        running = app.is_running
    finally:
        gate.set()

    assert held is True
    assert kept == {a1: 1}
    assert seen[1].stem == a2
    assert running is False


async def test_a_row_never_moves_while_the_scan_runs_and_the_order_settles_at_the_end(
    fake: FakeClaude, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Msgs cells fill in where the rows stand, even when Msgs orders the rows.

    A row that moved under the user's hand would be a trap, so the new order
    comes once, when the scan ends.
    """
    mid, top, low = new_id(), new_id(), new_id()
    for sid, prompts, mtime in ((mid, 1, 3000), (top, 2, 2000), (low, 0, 1000)):
        records = session_records(sid, "/p/x", custom_title=sid[:4])
        records += [prompt_record(sid, "More") for _ in range(prompts)]
        fake.transcript("/p/x", sid, records, mtime=mtime)
    gate = threading.Event()
    seen = gated_scan(monkeypatch, gate, hold=3)
    app = ConclaudeApp(settings)
    try:
        async with app.run_test(size=WIDE) as pilot:
            await pilot.pause()
            table = app.query_one(SessionsPane)
            await pilot.press("tab", "o", "o")
            await pilot.pause()
            start = rows(table), table.sorting
            await pilot.press("S")
            held = await until(lambda: len(seen) == 3, pilot)
            painted = await until(
                lambda: str(table.get_cell(top, "msgs")) == "3", pilot
            )
            during = rows(table), [str(table.get_cell(s, "msgs")) for s in rows(table)]
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            ended = rows(table), [str(table.get_cell(s, "msgs")) for s in rows(table)]
            cursor = table.selected_id
    finally:
        gate.set()

    assert start == ([mid, top, low], ("msgs", True))
    assert (held, painted) == (True, True)
    # The busiest session is on the middle row, and it stays there until the end
    assert during == ([mid, top, low], ["2", "3", ""])
    assert ended == ([top, mid, low], ["3", "2", "1"])
    assert cursor == mid


async def test_a_transcript_that_will_not_read_says_why_and_the_scan_walks_on(
    fake: FakeClaude, settings: Settings
) -> None:
    """One session that fails stops itself alone. Its cell stays blank, the rest fill."""
    a1, a2, b1 = three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        (settings.projects_dir / encode_project("/p/a") / f"{a1}.jsonl").unlink()
        await pilot.press("tab", "S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        cells = {sid: str(table.get_cell(sid, "msgs")) for sid in rows(table)}
        shown = toasts(app)

    assert cells == {a1: "", a2: "1", b1: "1"}
    assert [severity for severity, _title, _message in shown] == [
        "information",
        "error",
        "information",
    ]
    assert shown[1][1] == "Not scanned"
    assert "could not read" in shown[1][2]
    assert shown[2][2] == "2 scanned, 0 already fresh, 1 failed"


async def test_a_scan_does_not_pull_the_list_from_under_the_cursor(
    fake: FakeClaude, settings: Settings
) -> None:
    """A scan changes numbers, not places.

    The user scrolls down a long list and points at a row. The rows on view
    stay on view, and the row under the cursor keeps its line on the screen.
    """
    for index in range(20):
        sid = new_id()
        fake.transcript("/p/x", sid, session_records(sid, "/p/x"), mtime=1000 + index)
    app = ConclaudeApp(settings)
    async with app.run_test(size=(120, 16)) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab")
        # To the last row, so the list is scrolled to its end, then two rows up:
        # the cursor now has two rows below it, on view.
        await pilot.press(*["down"] * 19, "up", "up")
        await pilot.pause()
        before = table.scroll_offset.y, table.cursor_row
        await pilot.press("s")
        await app.workers.wait_for_complete()
        await pilot.pause()
        after = table.scroll_offset.y, table.cursor_row
        cell = str(table.get_cell(table.selected_id or "", "msgs"))

    assert before[0] > 0
    assert after == before
    assert cell == "1"


async def test_a_change_of_width_keeps_the_rows_on_view_where_they_are(
    fake: FakeClaude, settings: Settings
) -> None:
    """The same rule holds for a resize: the row under the cursor keeps its line.

    A resize rebuilds the table to refit the columns. That is the same clear
    and refill a scan ends with, so the list must stay as still.
    """
    for index in range(20):
        sid = new_id()
        fake.transcript("/p/x", sid, session_records(sid, "/p/x"), mtime=1000 + index)
    app = ConclaudeApp(settings)
    async with app.run_test(size=(120, 16)) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab")
        await pilot.press(*["down"] * 19, "up", "up")
        await pilot.pause()
        before = table.scroll_offset.y, table.cursor_row, table.selected_id
        await pilot.resize_terminal(130, 16)
        await pilot.pause()
        after = table.scroll_offset.y, table.cursor_row, table.selected_id

    assert before[0] > 0
    assert after == before
