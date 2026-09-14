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
from pathlib import Path

from textual.color import Color, ColorParseError
from textual.theme import BUILTIN_THEMES
from textual.widgets import DataTable, Static

import conclaude.tui.app
from conclaude.core.format import Formatter
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from conclaude.tui.app import ConclaudeApp, MainScreen
from conclaude.tui.panes import (
    ALL_PROJECTS,
    DetailsPane,
    FilterBox,
    ProjectsPane,
    SessionsPane,
)
from tests.fabricate import FakeClaude, FakeProc, new_id, session_records

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
        projects = app.query_one(ProjectsPane).region
        sessions = app.query_one(SessionsPane).region
        details = app.query_one(DetailsPane).region

    assert projects.x == 0
    assert projects.right == sessions.x == details.x
    assert sessions.y == 0
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
    for pane in (ProjectsPane, SessionsPane, DetailsPane):
        keys = {binding.key for binding in pane.__dict__["BINDINGS"]}
        assert {"tab", "q"} <= keys, pane.__name__


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
