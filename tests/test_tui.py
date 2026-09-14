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

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from textual.color import Color, ColorParseError
from textual.theme import BUILTIN_THEMES
from textual.widgets import DataTable, Header, Static

import conclaude.tui.app
from conclaude.core.format import Formatter
from conclaude.core.model import TrashEntry
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from conclaude.core.trash import trash_session
from conclaude.tui.app import ConclaudeApp, MainScreen, TrashScreen
from conclaude.tui.panes import (
    ALL_DAYS,
    ALL_PROJECTS,
    DaysPane,
    DetailsPane,
    EntriesPane,
    EntryPane,
    FilterBox,
    ProjectsPane,
    SessionsPane,
)
from tests.fabricate import FakeClaude, FakeProc, new_id, session_records, snapshot

WIDE = (140, 40)


def columns(table: DataTable) -> list[str]:
    """The column labels, left to right."""
    return [str(column.label) for column in table.columns.values()]


def rows(table: DataTable) -> list[str]:
    """The session ids, top to bottom."""
    return [str(row.key.value) for row in table.ordered_rows]


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


async def test_three_panes_projects_left_sessions_upper_right_details_lower_right(
    fake: FakeClaude, settings: Settings
) -> None:
    """Three panes: projects left, sessions upper right, details lower right."""
    three_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        header = app.query_one(Header).region
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

    assert labels == ["Title", "Last used ▼", "Size", "Msgs", "Project"]
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

    assert in_a == ([a1, a2], ["Title", "Last used ▼", "Size", "Msgs"], "/p/a")
    assert in_b == ([b1], "/p/b")


async def test_the_columns_hold_title_last_used_size_and_an_empty_turn_count(
    fake: FakeClaude, settings: Settings
) -> None:
    """The columns hold the title, last used, size and an empty turn count."""
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
            for key in ("title", "last_used", "size", "msgs")
        ]

    assert cells == [
        "Hello",
        fmt.timestamp(session.last_used),
        fmt.size(session.size),
        "",
    ]


async def test_live_and_fork_marks_sit_on_the_title(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """Live and fork marks sit on the title."""
    running, parent, child = new_id(), new_id(), new_id()
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
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        titles = {
            sid: str(table.get_cell(sid, "title")) for sid in (running, parent, child)
        }

    assert titles[running] == "dev:app [live]"
    assert titles[child] == "Kid [fork]"
    assert titles[parent] == "Mum"


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
        text = app.query_one(DetailsPane).text
        static = app.query_one("#details-text", Static)
        painted = str(static.render())

    assert painted == text
    for label, value in fmt.describe(store.details(sid)):
        assert re.search(
            rf"^{re.escape(label)}: +{re.escape(value)}$", text, re.M
        ), label
    assert f"Id:          {sid}" in text
    assert "Project:     /p/x  (from transcript)" in text
    assert "Git branch:  dev" in text
    assert f"Created:     {fmt.timestamp(session.created)}" in text
    assert f"Last used:   {fmt.timestamp(session.last_used)}" in text
    assert "Claude Code: 2.1.270" in text
    assert f"Transcript:  {fmt.size(session.transcript_size)}  " in text
    assert f"Sidecar:     {fmt.size(session.sidecar_size)}  " in text
    assert "(3 subagent transcripts)" in text
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
        assert {"tab", "q", "r", "t"} <= keys, pane.__name__


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
    assert "enter" in keys[0]
    assert "enter" not in keys[1]
    assert "enter" not in keys[2]
    for listed in keys:
        assert {"tab", "q"} <= set(listed)


async def test_enter_on_a_project_moves_into_its_sessions(
    fake: FakeClaude, settings: Settings
) -> None:
    """Enter on a project moves into its sessions."""
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
    """Q quits from every pane."""
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
    """R reloads. The cursor finds its session by id, not by row number."""
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
        ["Title", "Last used ▼", "Size", "Msgs", "Project"],
    )
    assert by_title == (
        ([b1, a1, a2], b1, ("title", False)),
        ["Title ▲", "Last used", "Size", "Msgs", "Project"],
    )


async def test_o_orders_by_the_next_column_and_the_cursor_stays_on_its_session(
    fake: FakeClaude, settings: Settings
) -> None:
    """O orders by the next column, O turns it round. The cursor stays on its session."""
    a1, a2, b1 = sized_sessions(fake)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        table = app.query_one(SessionsPane)
        await pilot.press("tab", "down")
        await pilot.pause()
        seen = [state(table)]
        for key in ("o", "O", "o", "o", "o", "o"):
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
        ([b1, a1, a2], a2, ("title", False)),
        ([a1, a2, b1], a2, ("last_used", True)),
    ]
    assert marked == ["Title", "Last used ▼", "Size", "Msgs", "Project"]


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
        for _ in range(4):
            await pilot.press("o")
            await pilot.pause()
            seen.append(table.sorting[0])

    assert seen == ["size", "msgs", "title", "last_used"]


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
        await pilot.click(SessionsPane, offset=(2, 1))
        await pilot.pause()
        once = state(table)
        await pilot.click(SessionsPane, offset=(2, 1))
        await pilot.pause()
        twice = state(table)

    assert once == ([b1, a1, a2], a2, ("title", False))
    assert twice == ([a2, a1, b1], a2, ("title", True))


async def test_slash_opens_a_box_that_narrows_the_sessions_as_you_type(
    fake: FakeClaude, settings: Settings
) -> None:
    """Slash opens a box. The sessions narrow by title as you type, case aside."""
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
    """Enter keeps the filter and goes back to the pane. Escape there clears it."""
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
    """Slash on the projects pane narrows the projects by path."""
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
    """D moves the session under the cursor to the Trash. Its row goes. Nothing reloads."""
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
    """D has no effect while another pane has the focus, and is not listed there."""
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
    """T switches the panes to the Trash. T again brings the sessions back as they were."""
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
        header = app.screen.query_one(Header).region
        left = app.screen.query_one(DaysPane).region
        upper = table.region
        lower = app.screen.query_one(EntryPane).region
        await pilot.press("t")
        await pilot.pause()
        sessions = app.screen.query_one(SessionsPane)
        after = type(app.screen), type(app.focused), cursor(sessions)

    assert before == (MainScreen, SessionsPane, "Trash")
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
        await pilot.press("down")
        await pilot.pause()
        second = pane.text

    assert painted == first
    for label, value in fmt.describe_entry(entry):
        assert re.search(
            rf"^{re.escape(label)}: +{re.escape(value)}$", first, re.M
        ), label
    assert re.search(rf"^Session: +{sid}$", first, re.M)
    assert re.search(rf"^Trashed: +{re.escape(fmt.timestamp(later))}$", first, re.M)
    assert re.search(r"^Reason: +pressed d$", first, re.M)
    assert re.search(rf"^Size: +{re.escape(fmt.size(entry.size))}$", first, re.M)
    for kind in ("transcript", "sidecar", "session-env", "file-history", "todo"):
        where = re.escape(str(parts[kind]))
        assert re.search(rf"^{kind.capitalize()}: +\S+  {where}$", first, re.M), kind
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


async def test_the_header_shows_what_the_trash_holds_and_follows_every_change(
    fake: FakeClaude, settings: Settings
) -> None:
    """The header shows the total Trash size. It follows a delete, a restore and a purge."""
    a1, _a2, b1 = three_sessions(fake)
    store = SessionStore(settings)
    a1_size = store.find_session(a1).size
    long_ago = datetime(2020, 1, 1, tzinfo=timezone.utc)
    old = trash_session(settings, store.find_session(b1), now=long_ago)
    fmt = Formatter(settings)
    app = ConclaudeApp(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        header = app.screen.query_one(Header)
        at_start = header.screen_title, header.screen_sub_title, app.sub_title
        await pilot.press("tab", "d")
        await pilot.pause()
        after_delete = app.sub_title
        await pilot.press("t")
        await pilot.pause()
        in_trash = app.screen.query_one(Header).screen_sub_title
        await pilot.press("u")
        await pilot.pause()
        after_restore = app.sub_title
        await pilot.press("x")
        await pilot.pause()
        after_purge = app.sub_title
        await pilot.press("t")
        await pilot.pause()
        back = app.screen.query_one(Header).screen_sub_title

    one = f"Trash: 1 entry, {fmt.size(old.size)}"
    two = f"Trash: 2 entries, {fmt.size(old.size + a1_size)}"
    assert at_start == ("conclaude", one, one)
    assert after_delete == two
    assert in_trash == two
    assert after_restore == one
    assert after_purge == "Trash: empty"
    assert back == "Trash: empty"


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
            app.sub_title,
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

    assert empty == ([ALL_DAYS], ([], None, 0), "No entry.", "Trash: empty")
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
        after = cursor(table), app.sub_title

    assert before == ([first.id], first.id, 0)
    assert after == (
        ([second.id, first.id], first.id, 1),
        f"Trash: 2 entries, {fmt.size(first.size + second.size)}",
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


async def test_a_long_title_is_cut_in_the_middle_and_keeps_its_end_and_its_marks(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """A long title is cut in the middle, by the character. Its end and its marks stay."""
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

    assert 0 < width < len(TALE)
    assert cells == [
        fmt.title(f"{TALE}, part one", width),
        fmt.title(f"{TALE}, part two [live]", width),
    ]
    assert cells[0].endswith("part one") and cells[1].endswith("part two [live]")
    assert settings.cut_mark in cells[0]


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
