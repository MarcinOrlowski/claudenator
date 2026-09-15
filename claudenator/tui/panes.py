"""
##################################################################################
#
# Claudenator by Marcin Orlowski
# The only Claude Code session manager you need.
#
# @author    Marcin Orlowski <mail@marcinOrlowski.com>
# Copyright  ©2026 Marcin Orlowski <MarcinOrlowski.com>
# @link      https://github.com/MarcinOrlowski/claudenator
#
##################################################################################
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Input, OptionList, Static
from textual.widgets.option_list import Option, OptionDoesNotExist

from claudenator import __title__, __version__
from claudenator.core.format import Formatter
from claudenator.core.model import Figures, Project, Session, SessionDetails, TrashEntry
from claudenator.core.store import sort_key

# The keys every pane uses
SHARED_BINDINGS = [
    Binding("tab", "app.focus_next", "Next pane"),
    Binding("shift+tab", "app.focus_previous", "Previous pane", show=False),
    Binding("r", "screen.reload", "Reload"),
    Binding("f2", "app.settings", "Settings"),
    # The title bar shows this key, so the footer keeps the room for the rest.
    Binding("question_mark", "app.about", "About", key_display="?", show=False),
    Binding("q", "app.quit", "Quit"),
]

# The key that switches between the sessions and the Trash view.
TO_TRASH = Binding("t", "screen.trash_mode", "Trash")
TO_SESSIONS = Binding("t", "screen.sessions_mode", "Sessions")


def label_trash_key(screen: Widget, label: str) -> None:
    """Put ``label`` on the key that opens the Trash, on every pane under ``screen``.

    The footer takes a key's label from the binding map of the pane that has the
    focus, and the library gives no public way to change a label once the pane
    is up. So this puts a copy of the binding, with the new label, into the map
    of every pane that has the key. ``refresh_bindings`` makes the footer redraw.
    """
    binding = replace(TO_TRASH, description=label)
    for pane in screen.query(Widget):
        bindings = pane._bindings.key_to_bindings
        if any(b.action == TO_TRASH.action for b in bindings.get(TO_TRASH.key, ())):
            bindings[TO_TRASH.key] = [binding]
            pane.refresh_bindings()


# The keys of a pane that can narrow its list to a typed text
FILTER_BINDINGS = [
    Binding("slash", "filter", "Filter", key_display="/"),
    Binding("escape", "clear_filter", "Clear filter"),
]

ALL_PROJECTS = "All projects"
ALL_DAYS = "All days"

# Room kept for the vertical scrollbar of a table.
SCROLLBAR_WIDTH = 2

# A flexible column is never squeezed below this limit.
NARROWEST_COLUMN = 12

# When two flexible columns share the room that the fixed columns leave,
# this is the first one's part of it.
TITLE_SHARE = 0.6

# The columns of the sessions table.
COLUMNS = {
    "state": "Sts",
    "title": "Title",
    "last_used": "Last used",
    "size": "Size",
    "msgs": "Msgs",
    "project": "Project",
}

# The columns of the Trash table.
ENTRY_COLUMNS = {
    "title": "Title",
    "trashed_at": "Trashed",
    "size": "Size",
    "project": "Project",
}

# A number or a time column sorts biggest value first when its column is chosen.
# The state column goes with them, so the live sessions come to the top.
# The other columns do alpha sort.
BIGGEST_FIRST = {"state", "last_used", "size", "msgs"}

# The mark on the label of the column that sorts the rows.
SORT_MARK = {True: " ▼", False: " ▲"}

# The colours a session row can take. The stylesheet gives each one a theme
# variable, so all 20 themes fit. See ``state_class``.
STATE_CLASSES = {"sessions--damaged", "sessions--live", "sessions--fork"}


def state_class(session: Session) -> str:
    """The class that colours the row of ``session``, or ``""`` for the plain colour.

    A row holds one colour only, so the states come in an order: a damaged
    session first, then a live one, then a fork. The State column says the same
    thing in letters, so the colour is never the only clue.
    """
    if session.damaged:
        return "sessions--damaged"
    if session.live:
        return "sessions--live"
    if session.is_fork:
        return "sessions--fork"
    return ""


def flexible_widths(room: int, padding: int, two: bool) -> tuple[int, int]:
    """How wide one or two flexible cols can be in the room the fixed ones leave."""
    if not two:
        return max(room - padding, NARROWEST_COLUMN), 0
    room -= 2 * padding
    first = max(int(room * TITLE_SHARE), NARROWEST_COLUMN)
    return first, max(room - first, NARROWEST_COLUMN)


@dataclass(frozen=True)
class Place:
    """Where the cursor of a table is, so that a rebuild can put it back.

    ``key`` names the row it points at, ``index`` is the row it sits on, and
    ``line`` is how far below the top row on view that row is drawn.
    """

    key: str | None
    index: int
    line: int


class FilterWanted(Message):
    """A pane asks for its filter box: to type in it, or to clear it."""

    def __init__(self, pane: Widget, clear: bool = False) -> None:
        super().__init__()
        self.pane = pane
        self.clear = clear


class Filterable:
    """A pane that can narrow its list to the lines that hold a typed text."""

    _filter = ""

    @property
    def filter_text(self) -> str:
        """The text in effect. Empty when the list is not narrowed."""
        return self._filter

    def set_filter(self, text: str) -> None:
        """Narrow the list to the lines that hold ``text``. Empty text keeps all."""
        if text == self._filter:
            return
        self._filter = text
        self._rebuild()
        self.refresh_bindings()

    def _matches(self, line: str) -> bool:
        """True when the text in effect lets this line through. Case does not count."""
        return self._filter.casefold() in line.casefold()

    def action_filter(self) -> None:
        """The '/' key: the user wants to type a filter."""
        self.post_message(FilterWanted(self))

    def action_clear_filter(self) -> None:
        """The 'escape' key: the list goes back to full."""
        self.post_message(FilterWanted(self, clear=True))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """List 'Clear filter' only while a filter is in effect."""
        if action == "clear_filter":
            return bool(self._filter)
        return super().check_action(action, parameters)


class FilterBox(Input):
    """The line under a pane where the user types its filter.

    Shown while the user types, and while a filter is in effect. 'enter'
    goes back to the pane and keeps the filter. 'escape' drops it and goes back.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Clear"),
        Binding("enter", "submit", "Done"),
    ]

    def __init__(self, pane: Widget) -> None:
        super().__init__(id=f"{pane.id}-filter")
        self.border_title = "Filter"
        self.pane = pane
        self.display = False

    def open(self) -> None:
        """Show the box with the filter in effect and let the user type."""
        self.value = self.pane.filter_text
        self.display = True
        self.focus()
        self.cursor_position = len(self.value)

    def action_cancel(self) -> None:
        """The 'escape' key: the filter goes, the pane gets the focus back."""
        self.value = ""
        self._close()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Every keystroke narrows the pane at once."""
        event.stop()
        self.pane.set_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """The 'enter' key: the filter stays, the pane gets the focus back."""
        event.stop()
        self._close()

    def on_blur(self) -> None:
        """Focus went elsewhere: same as a close."""
        self._close()

    def _close(self) -> None:
        """Back to the pane. The box stays in view only while it holds a filter."""
        self.display = bool(self.value)
        self.pane.focus()


class Lister(OptionList):
    """A left pane: one 'all' line, then one line per thing.

    The highlight is held as an id, never as an index. Every subclass names
    its own ``Chosen`` and ``Opened``, so a screen can tell the panes apart.
    """

    class Chosen(Message):
        """The highlight moved. ``key`` is None on the 'all' line."""

        def __init__(self, key: str | None) -> None:
            super().__init__()
            self.key = key

    class Opened(Message):
        """The user pressed 'enter' on a line: they want to work on what it holds."""

    def __init__(self, id: str, title: str, fmt: Formatter) -> None:
        super().__init__(id=id)
        self.border_title = title
        self.fmt = fmt
        self._title = title
        self._selected: str | None = None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Turn the widget's own message into one that names the line."""
        event.stop()
        self._selected = event.option_id
        self.post_message(self.Chosen(event.option_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """The 'enter' key on a line."""
        event.stop()
        self.post_message(self.Opened())

    def repaint(self) -> None:
        """Write every line again, for a setting that changes how a line reads."""
        self._relabel()

    def _label(self, key: str) -> str:
        """The text of one line. The id itself, unless a subclass makes it fit."""
        return key

    def _relabel(self) -> None:
        """Write the text of every line again, with the highlight left alone."""
        for index, option in enumerate(self.options):
            if option.id is not None:
                self.replace_option_prompt_at_index(
                    index, Content(self._label(option.id))
                )

    def _refill(self, first: str, ids: list[str]) -> None:
        """Put the lines back: the 'all' line, then one per id. The title counts them."""
        self.border_title = self.fmt.counted(self._title, len(ids))
        wanted = self._selected
        index = self.highlighted or 0
        self.clear_options()
        self.add_option(Option(Content(first), id=None))
        self.add_options(Option(Content(self._label(key)), id=key) for key in ids)
        if wanted is None:
            index = 0
        else:
            try:
                index = self.get_option_index(wanted)
            except OptionDoesNotExist:
                index = min(index, self.option_count - 1)
        # ``clear_options`` dropped the highlight
        self.highlighted = index


class ProjectsPane(Filterable, Lister):
    """The left pane: every project with a session, under one 'All projects' line."""

    BINDINGS = [
        *SHARED_BINDINGS,
        TO_TRASH,
        *FILTER_BINDINGS,
        Binding("enter", "select", "Sessions"),
    ]

    class Chosen(Lister.Chosen):
        """The highlight moved. ``path`` is None on the 'All projects' line."""

        def __init__(self, path: str | None) -> None:
            super().__init__(path)
            self.path = path

    class Opened(Lister.Opened):
        """The user pressed 'enter' on a project: they want to work on its sessions."""

    def __init__(self, fmt: Formatter) -> None:
        super().__init__("projects", "Projects", fmt)
        self._projects: list[Project] = []
        # The columns one line has for its path. Unknown until the first resize.
        self._room = 0

    @property
    def selected_path(self) -> str | None:
        """The path of the highlighted project, or None for 'All projects'."""
        return self._selected

    def show(self, projects: list[Project]) -> None:
        """Replace the list. The highlight stays on its project when it is still there."""
        self._projects = list(projects)
        self._rebuild()

    def on_resize(self) -> None:
        """Write the paths again when the room for them changes."""
        room = self._measure()
        if room != self._room:
            self._room = room
            self._relabel()

    def _measure(self) -> int:
        """The columns one line has for its text, the scrollbar and padding aside."""
        padding = self.get_component_styles("option-list--option").padding.width
        return self.scrollable_content_region.width - padding

    def _label(self, key: str) -> str:
        """The path, cut in the middle when the line has no room for all of it."""
        return self.fmt.path(key, self._room) if self._room > 0 else key

    def _rebuild(self) -> None:
        """Put the lines back, with the filter in effect."""
        self._refill(
            ALL_PROJECTS,
            [project.path for project in self._projects if self._matches(project.path)],
        )


class DaysPane(Lister):
    """The left pane in Trash mode: the days on which something was trashed."""

    BINDINGS = [
        *SHARED_BINDINGS,
        TO_SESSIONS,
        Binding("enter", "select", "Entries"),
    ]

    class Chosen(Lister.Chosen):
        """The highlight moved. ``day`` is None on the 'All days' line."""

        def __init__(self, day: str | None) -> None:
            super().__init__(day)
            self.day = day

    class Opened(Lister.Opened):
        """The user pressed 'enter' on a day: they want to work on its entries."""

    def __init__(self, fmt: Formatter) -> None:
        super().__init__("days", "Days", fmt)
        self._days: list[str] = []

    @property
    def selected_day(self) -> str | None:
        """The highlighted day, or None for 'All days'."""
        return self._selected

    def show(self, entries: list[TrashEntry]) -> None:
        """Replace the days with the ones these entries went in on, newest first.

        The highlight stays on its day when it is still there.
        """
        days: list[str] = []
        for entry in entries:
            day = self.fmt.day(entry.trashed_at)
            if day not in days:
                days.append(day)
        self._days = days
        self._refill(ALL_DAYS, self._days)


class Table(Filterable, DataTable):
    """An upper right pane."""

    # The actions that need a row under the cursor. They dim with an empty table.
    ROW_ACTIONS: frozenset[str] = frozenset()
    # What one row is, for the title: ``session`` or ``entry``.
    NOUN = "row"

    class Chosen(Message):
        """The cursor moved to a row, or the table went empty (``None``)."""

        def __init__(self, key: str | None) -> None:
            super().__init__()
            self.key = key

    def __init__(self, id: str, title: str, fmt: Formatter) -> None:
        super().__init__(id=id, cursor_type="row")
        self.border_title = title
        self.fmt = fmt
        self._title = title
        self._selected: str | None = None
        self._widths: tuple[int, int] = (0, 0)

    @property
    def selected_id(self) -> str | None:
        """The key of the row under the cursor, or None when there is none."""
        return self._selected

    def drop(self, key: str) -> None:
        """Take one row out of the table in place."""
        if self.rows.get(key) is not None:
            self.remove_row(key)
        self._retitle()
        self._announce()

    def repaint(self) -> None:
        """Put every row back, for a setting that changes how a cell reads."""
        self._rebuild()

    def _rows(self) -> Sequence[Session | TrashEntry]:
        """The rows on view: the filter in effect, in the order in effect."""
        raise NotImplementedError

    def _rebuild(self) -> None:
        """Put the rows back. Every table has its own columns and cells."""
        raise NotImplementedError

    def _retitle(self) -> None:
        """The title counts the rows on view and sums their size."""
        sizes = [row.size for row in self._rows()]
        self.border_title = self.fmt.summary(self._title, self.NOUN, sizes)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Dim the keys that need a row while there is none to act on."""
        if action in self.ROW_ACTIONS:
            return True if self.row_count else None
        return super().check_action(action, parameters)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Turn the widget's own message into one that names the row."""
        event.stop()
        self._select(event.row_key.value)

    def _select(self, key: str | None) -> None:
        self._selected = key
        self.post_message(self.Chosen(key))

    def _announce(self) -> None:
        """Say what the cursor sits on now, even when no row event will."""
        if not self.row_count:
            self._select(None)
        else:
            cell = self.coordinate_to_cell_key(self.cursor_coordinate)
            self._select(cell.row_key.value)
        # The keys that need a row dim with an empty table and come back with one
        self.refresh_bindings()

    def _place(self) -> Place:
        """Where the cursor is right now, to hand to ``_place_cursor`` after a rebuild."""
        return Place(
            self._selected, self.cursor_row, self.cursor_row - self.scroll_offset.y
        )

    def _place_cursor(self, place: Place) -> None:
        """After a rebuild, the cursor finds its row by key, or takes the row it was on."""
        if self.row_count:
            index = place.index
            if place.key is not None and self.rows.get(place.key) is not None:
                index = self.get_row_index(place.key)
            self.move_cursor(row=min(index, self.row_count - 1), animate=False)
            room = max(self.scrollable_content_region.height - 1, 0)
            line = min(max(place.line, 0), room)
            self.scroll_to(y=max(self.cursor_row - line, 0), animate=False)
        self._announce()


class SessionsPane(Table):
    """The upper right pane: the sessions of one project."""

    BINDINGS = [
        *SHARED_BINDINGS,
        TO_TRASH,
        *FILTER_BINDINGS,
        Binding("d", "trash", "Delete"),
        Binding("s", "scan", "Scan"),
        Binding("S", "scan_all", "Scan all"),
        Binding("o", "sort_next", "Sort"),
        Binding("O", "sort_reverse", "Reverse"),
        Binding("enter", "open", "Details"),
    ]
    ROW_ACTIONS = frozenset({"trash", "open", "scan", "scan_all"})
    NOUN = "session"
    COMPONENT_CLASSES = STATE_CLASSES

    class Chosen(Table.Chosen):
        """The cursor moved to a session, or the table went empty (``None``)."""

        def __init__(self, session_id: str | None) -> None:
            super().__init__(session_id)
            self.session_id = session_id

    class TrashWanted(Message):
        """The user pressed d: the session under the cursor goes to the Trash."""

        def __init__(self, session: Session) -> None:
            super().__init__()
            self.session = session

    class Opened(Message):
        """The user pressed 'enter': they want this session in full, over the window."""

        def __init__(self, session: Session) -> None:
            super().__init__()
            self.session = session

    class ScanWanted(Message):
        """The user pressed 's': the session under the cursor wants a deep scan."""

        def __init__(self, session: Session) -> None:
            super().__init__()
            self.session = session

    class ScanAllWanted(Message):
        """The user pressed 'S': every session on view wants a deep scan."""

        def __init__(self, sessions: list[Session]) -> None:
            super().__init__()
            self.sessions = sessions

    def __init__(self, fmt: Formatter) -> None:
        super().__init__("sessions", "Sessions", fmt)
        self._sessions: list[Session] = []
        self._by_id: dict[str, Session] = {}
        self._figures: dict[str, Figures] = {}
        self._with_project = False
        self._sort_column = "last_used"
        self._sort_descending = True

    @property
    def selected(self) -> Session | None:
        """The session under the cursor, or None when there is none."""
        if self._selected is None:
            return None
        return self._by_id.get(self._selected)

    @property
    def sorting(self) -> tuple[str, bool]:
        """The column that orders the rows, and whether it is biggest first."""
        return self._sort_column, self._sort_descending

    @property
    def listed(self) -> list[Session]:
        """The sessions on view right now: the project choice and the filter in effect."""
        return self._rows()

    def show(
        self,
        sessions: list[Session],
        with_project: bool,
        figures: dict[str, Figures] | None = None,
    ) -> None:
        """Replace the rows. The cursor stays on its session when it is still listed.

        The Project column is shown only when ``with_project`` is true, which
        is the 'All projects' view. ``figures`` hold the cached deep-scan
        numbers by session id, and fill the Msgs column. A session with none
        gets a blank cell.
        """
        self._sessions = list(sessions)
        self._by_id = {session.id: session for session in self._sessions}
        self._figures = dict(figures or {})
        self._with_project = with_project
        self._rebuild()

    def _turns(self, session: Session) -> str:
        """The Msgs cell: the cached turn count, ``*12`` when stale, blank with none."""
        figures = self._figures.get(session.id)
        if figures is None:
            return ""
        return self.fmt.stale(self.fmt.count(figures.turns), figures)

    def set_figures(self, session_id: str, figures: Figures) -> None:
        """Put the figures of one session on its row, where the row stands.

        The Msgs cell alone changes, and the column widens for it when it has
        to. No row moves, so a scan that runs while the user works never pulls
        a row out from under the cursor. ``reorder`` does that, once, at the end.
        """
        self._figures[session_id] = figures
        session = self._by_id.get(session_id)
        if session is None or self.rows.get(session_id) is None:
            return
        self.update_cell(
            session_id,
            "msgs",
            Text(self._turns(session), justify="right"),
            update_width=True,
        )

    def reorder(self) -> None:
        """Put the rows back in the order in effect, with every figure that came in since.

        The cursor holds its session, as it does after any other rebuild.
        """
        if self._sessions:
            self._rebuild()

    def drop(self, session_id: str) -> None:
        """Take one session out of the table in place."""
        self._sessions = [s for s in self._sessions if s.id != session_id]
        self._by_id.pop(session_id, None)
        super().drop(session_id)

    def action_trash(self) -> None:
        """The 'd' key: ask for the session under the cursor to go to the Trash."""
        session = self.selected
        if session is not None:
            self.post_message(self.TrashWanted(session))

    def action_open(self) -> None:
        """The 'enter' key: ask for the session under the cursor in full."""
        session = self.selected
        if session is not None:
            self.post_message(self.Opened(session))

    def action_scan(self) -> None:
        """The 's' key: ask for a deep scan of the session under the cursor."""
        session = self.selected
        if session is not None:
            self.post_message(self.ScanWanted(session))

    def action_scan_all(self) -> None:
        """The 'S' key: ask for a deep scan of every session on view."""
        sessions = self.listed
        if sessions:
            self.post_message(self.ScanAllWanted(sessions))

    def sort_by(self, column: str, descending: bool | None = None) -> None:
        """Order the rows by one column.

        With ``descending`` left out, a number or a time goes biggest first
        and a text goes alpha order. The cursor stays on its session.
        """
        if descending is None:
            descending = column in BIGGEST_FIRST
        self._sort_column = column
        self._sort_descending = descending
        if self._sessions:
            self._rebuild()

    def action_sort_next(self) -> None:
        """The 'o' key: order by the next column along."""
        shown = self._shown_columns()
        try:
            index = shown.index(self._sort_column)
        except ValueError:
            index = -1
        self.sort_by(shown[(index + 1) % len(shown)])

    def action_sort_reverse(self) -> None:
        """The 'O' key: the same column, the other way round."""
        self.sort_by(self._sort_column, not self._sort_descending)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """A click on a header orders by that column. A second click turns it round."""
        event.stop()
        column = str(event.column_key.value)
        if column == self._sort_column:
            self.action_sort_reverse()
        else:
            self.sort_by(column)

    def on_resize(self) -> None:
        """Refit the flexible columns when the room changes."""
        if self._sessions and self._fit() != self._widths:
            self._rebuild()

    def _shown_columns(self) -> list[str]:
        """The keys of the columns on view, left to right."""
        return [key for key in COLUMNS if key != "project" or self._with_project]

    def _labels(self) -> dict[str, str]:
        """The header of every column on view, with the sort mark on one of them."""
        labels = {key: COLUMNS[key] for key in self._shown_columns()}
        if self._sort_column in labels:
            labels[self._sort_column] += SORT_MARK[self._sort_descending]
        return labels

    def _rows(self) -> list[Session]:
        """The sessions on view: the filter in effect, in the order in effect."""
        kept = [s for s in self._sessions if self._matches(s.title)]
        return sorted(
            kept,
            key=sort_key(self._sort_column, self._figures),
            reverse=self._sort_descending,
        )

    def _state_width(self, labels: dict[str, str]) -> int:
        """How wide the State column is."""
        return max(len(labels["state"]), self.fmt.state_width)

    def _fit(self) -> tuple[int, int]:
        """How wide the Title and Project columns can be with the room on hand."""
        labels = self._labels()
        padding = 2 * self.cell_padding
        times = [len(self.fmt.list_timestamp(s.last_used)) for s in self._sessions]
        sizes = [len(self.fmt.size(s.size)) for s in self._sessions]
        turns = [len(self._turns(s)) for s in self._sessions]
        fixed = (
            self._state_width(labels)
            + max([len(labels["last_used"]), *times])
            + max([len(labels["size"]), *sizes])
            + max([len(labels["msgs"]), *turns])
            + 4 * padding
        )
        room = self.size.width - SCROLLBAR_WIDTH - fixed
        return flexible_widths(room, padding, self._with_project)

    def _session_at(self, row_index: int) -> Session | None:
        """The session on the row at ``row_index``, or None when there is none."""
        if not 0 <= row_index < self.row_count:
            return None
        key = self.ordered_rows[row_index].key.value
        return self._by_id.get(key) if key is not None else None

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        """Give the row at ``row_index`` the colour of its state.

        The table asks for this every time it draws a row, so the colour
        follows the theme in effect with no rebuild, and the row under the
        cursor keeps the colours of the cursor. The class comes from
        ``state_class`` and the colour itself from the stylesheet.
        """
        style = super()._get_row_style(row_index, base_style)
        session = self._session_at(row_index)
        name = state_class(session) if session is not None else ""
        if not name:
            return style
        own = self.get_component_rich_style(name)
        # The colour alone goes on the row. The background stays as it is, so
        # the cursor, the hover and the pane itself all hold their own.
        return style + own.without_color + Style.from_color(color=own.color)

    def _rebuild(self) -> None:
        """Put the rows back."""
        place = self._place()
        labels = self._labels()
        self._widths = self._fit()
        title_width, project_width = self._widths
        self.clear(columns=True)
        self.add_column(labels["state"], key="state", width=self._state_width(labels))
        self.add_column(labels["title"], key="title", width=title_width)
        self.add_column(labels["last_used"], key="last_used")
        self.add_column(Text(labels["size"], justify="right"), key="size")
        self.add_column(Text(labels["msgs"], justify="right"), key="msgs")
        if self._with_project:
            self.add_column(labels["project"], key="project", width=project_width)
        for session in self._rows():
            cells: list[Text | str] = [
                self.fmt.marks(session),
                Text(
                    self.fmt.title(session.title, title_width),
                    no_wrap=True,
                    overflow="ellipsis",
                ),
                self.fmt.list_timestamp(session.last_used),
                Text(self.fmt.size(session.size), justify="right"),
                Text(self._turns(session), justify="right"),
            ]
            if self._with_project:
                cells.append(
                    Text(
                        self.fmt.path(session.project_path, project_width),
                        no_wrap=True,
                        overflow="ellipsis",
                    )
                )
            self.add_row(*cells, key=session.id)
        self._place_cursor(place)
        self._retitle()


class EntriesPane(Table):
    """The upper right pane in Trash mode: the entries of one day, newest first."""

    BINDINGS = [
        *SHARED_BINDINGS,
        TO_SESSIONS,
        *FILTER_BINDINGS,
        Binding("u", "restore", "Restore"),
        Binding("x", "purge", "Purge"),
        Binding("enter", "open", "Entry"),
    ]
    ROW_ACTIONS = frozenset({"restore", "purge", "open"})
    NOUN = "entry"

    class Chosen(Table.Chosen):
        """The cursor moved to an entry, or the table went empty (``None``)."""

        def __init__(self, entry_id: str | None) -> None:
            super().__init__(entry_id)
            self.entry_id = entry_id

    class RestoreWanted(Message):
        """The user pressed u: the entry under the cursor goes back where it came from."""

        def __init__(self, entry: TrashEntry) -> None:
            super().__init__()
            self.entry = entry

    class PurgeWanted(Message):
        """The user pressed x: the entry under the cursor leaves the disk for good."""

        def __init__(self, entry: TrashEntry) -> None:
            super().__init__()
            self.entry = entry

    class Opened(Message):
        """The user pressed 'enter': they want this entry in full, over the window."""

        def __init__(self, entry: TrashEntry) -> None:
            super().__init__()
            self.entry = entry

    def __init__(self, fmt: Formatter) -> None:
        super().__init__("entries", "Trash", fmt)
        self._entries: list[TrashEntry] = []
        self._by_id: dict[str, TrashEntry] = {}

    @property
    def selected(self) -> TrashEntry | None:
        """The entry under the cursor, or None when there is none."""
        if self._selected is None:
            return None
        return self._by_id.get(self._selected)

    def show(self, entries: list[TrashEntry]) -> None:
        """Replace the rows, in the order given. The cursor stays on its entry."""
        self._entries = list(entries)
        self._by_id = {entry.id: entry for entry in self._entries}
        self._rebuild()

    def drop(self, entry_id: str) -> None:
        """Take one entry out of the table in place."""
        self._entries = [e for e in self._entries if e.id != entry_id]
        self._by_id.pop(entry_id, None)
        super().drop(entry_id)

    def action_restore(self) -> None:
        """The 'u' key: ask for the entry under the cursor to go back."""
        entry = self.selected
        if entry is not None:
            self.post_message(self.RestoreWanted(entry))

    def action_purge(self) -> None:
        """The 'x' key: ask for the entry under the cursor to leave the disk."""
        entry = self.selected
        if entry is not None:
            self.post_message(self.PurgeWanted(entry))

    def action_open(self) -> None:
        """The 'enter' key: ask for the entry under the cursor in full."""
        entry = self.selected
        if entry is not None:
            self.post_message(self.Opened(entry))

    def on_resize(self) -> None:
        """Refit the flexible columns when the room changes."""
        if self._entries and self._fit() != self._widths:
            self._rebuild()

    def _rows(self) -> list[TrashEntry]:
        """The entries on view: the filter in effect, newest first."""
        return [e for e in self._entries if self._matches(e.title)]

    def _fit(self) -> tuple[int, int]:
        """How wide the Title and Project columns can be with the room on hand."""
        padding = 2 * self.cell_padding
        times = [len(self.fmt.list_timestamp(e.trashed_at)) for e in self._entries]
        sizes = [len(self.fmt.size(e.size)) for e in self._entries]
        fixed = (
            max([len(ENTRY_COLUMNS["trashed_at"]), *times])
            + max([len(ENTRY_COLUMNS["size"]), *sizes])
            + 2 * padding
        )
        room = self.size.width - SCROLLBAR_WIDTH - fixed
        return flexible_widths(room, padding, True)

    def _rebuild(self) -> None:
        """Put the rows back."""
        place = self._place()
        self._widths = self._fit()
        title_width, project_width = self._widths
        self.clear(columns=True)
        self.add_column(ENTRY_COLUMNS["title"], key="title", width=title_width)
        self.add_column(ENTRY_COLUMNS["trashed_at"], key="trashed_at")
        self.add_column(Text(ENTRY_COLUMNS["size"], justify="right"), key="size")
        self.add_column(ENTRY_COLUMNS["project"], key="project", width=project_width)
        for entry in self._rows():
            self.add_row(
                Text(
                    self.fmt.title(entry.title, title_width),
                    no_wrap=True,
                    overflow="ellipsis",
                ),
                self.fmt.list_timestamp(entry.trashed_at),
                Text(self.fmt.size(entry.size), justify="right"),
                Text(
                    self.fmt.path(entry.project_path, project_width),
                    no_wrap=True,
                    overflow="ellipsis",
                ),
                key=entry.id,
            )
        self._place_cursor(place)
        self._retitle()


class Lines(VerticalScroll):
    """A lower right pane: one thing in full, as label and value lines."""

    def __init__(self, id: str, title: str, fmt: Formatter, empty: str) -> None:
        super().__init__(id=id)
        self.border_title = title
        self.fmt = fmt
        self._empty = empty
        self._lines: list[tuple[str, str]] = []
        # The columns one line has. Unknown until the first resize.
        self._room = 0
        self.text = ""

    def compose(self) -> ComposeResult:
        """One block of text, scrolled by the pane around it."""
        yield Static(id=f"{self.id}-text", markup=False)

    def show_lines(self, lines: list[tuple[str, str]] | None) -> None:
        """Show these lines, or the empty state when there are none."""
        self._lines = list(lines or [])
        self._paint()

    def on_resize(self) -> None:
        """Write the lines again when the room for them changes."""
        room = self.scrollable_content_region.width
        if room != self._room:
            self._room = room
            if self._lines:
                self._paint()

    def repaint(self) -> None:
        """Write the lines again, for a setting that changes how one reads."""
        self._paint()

    def _paint(self) -> None:
        """Put the lines on the screen, each one cut to the room it has."""
        if not self._lines:
            self.text = self._empty
        else:
            width = max(len(label) for label, _ in self._lines) + 1
            room = self._room - width - 1
            self.text = "\n".join(
                f"{(label + ':').ljust(width)} "
                f"{self.fmt.fit(value, room) if self._room > 0 else value}"
                for label, value in self._lines
            )
        self.query_one(f"#{self.id}-text", Static).update(self.text)


class DetailsPane(Lines):
    """The lower right pane: one session in full, the same lines ``info`` prints."""

    BINDINGS = [*SHARED_BINDINGS, TO_TRASH]

    def __init__(self, fmt: Formatter) -> None:
        super().__init__("details", "Details", fmt, "No session.")

    def show(self, details: SessionDetails | None) -> None:
        """Show one session, or the empty state when there is none."""
        self.show_lines(self.fmt.describe(details) if details is not None else None)


class EntryPane(Lines):
    """The lower right pane in Trash mode: one entry in full, with every part."""

    BINDINGS = [*SHARED_BINDINGS, TO_SESSIONS]

    def __init__(self, fmt: Formatter) -> None:
        super().__init__("entry", "Entry", fmt, "No entry.")

    def show(self, entry: TrashEntry | None) -> None:
        """Show one entry, or the empty state when there is none."""
        self.show_lines(self.fmt.describe_entry(entry) if entry is not None else None)


class TooSmall(Static):
    """The message that takes the place of the panes in a window with no room."""

    def __init__(self, width: int, height: int) -> None:
        super().__init__(
            f"Window too small\nAt least {width} x {height}",
            id="too-small",
            markup=False,
        )
        self.display = False


class TitleBar(Horizontal):
    """The top line."""

    BRAND = f"{__title__} v{__version__}"

    # The 'about' key is the only key the footer does not list, so the title bar
    # carries it instead, in the colour the footer gives a key of its own.
    ABOUT_HINT = "(?)"

    def __init__(self, view: str) -> None:
        super().__init__(id="title-bar")
        self.view = view

    def compose(self) -> ComposeResult:
        yield Static(self.view, id="view", markup=False)
        yield Static(self.BRAND, id="brand", markup=False)
        yield Static(self.ABOUT_HINT, id="about-key", markup=False)
