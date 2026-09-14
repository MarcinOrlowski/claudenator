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

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Input, OptionList, Static
from textual.widgets.option_list import Option, OptionDoesNotExist

from conclaude.core.format import Formatter
from conclaude.core.model import Project, Session, SessionDetails
from conclaude.core.store import sort_key

# The keys every pane uses
SHARED_BINDINGS = [
    Binding("tab", "app.focus_next", "Next pane"),
    Binding("shift+tab", "app.focus_previous", "Previous pane", show=False),
    Binding("r", "screen.reload", "Reload"),
    Binding("q", "app.quit", "Quit"),
]

# The keys of a pane that can narrow its list to a typed text
FILTER_BINDINGS = [
    Binding("slash", "filter", "Filter", key_display="/"),
    Binding("escape", "clear_filter", "Clear filter"),
]

ALL_PROJECTS = "All projects"

# Room kept for the vertical scrollbar of the sessions table.
SCROLLBAR_WIDTH = 2

# A flexible column is never squeezed below this limit.
NARROWEST_COLUMN = 12

# In the 'All projects' view the Title and Project columns share the room
# that the fixed columns leave. This is the Title column's part of it.
TITLE_SHARE = 0.6

# The columns of the sessions table.
COLUMNS = {
    "title": "Title",
    "last_used": "Last used",
    "size": "Size",
    "msgs": "Msgs",
    "project": "Project",
}

# A number or a time column sorts biggest value first when its column is chosen.
# The other columns do alpha sort.
BIGGEST_FIRST = {"last_used", "size", "msgs"}

# The mark on the label of the column that sorts the rows.
SORT_MARK = {True: " ▼", False: " ▲"}


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
        """Slash: the user wants to type a filter."""
        self.post_message(FilterWanted(self))

    def action_clear_filter(self) -> None:
        """Escape: the list goes back to full."""
        self.post_message(FilterWanted(self, clear=True))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """List 'Clear filter' only while a filter is in effect."""
        if action == "clear_filter":
            return bool(self._filter)
        return super().check_action(action, parameters)


class FilterBox(Input):
    """The line under a pane where the user types its filter.

    Shown while the user types, and while a filter is in effect. ENTER
    goes back to the pane and keeps the filter. ESC drops filter and goes back.
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
        """Escape: the filter goes, the pane gets the focus back."""
        self.value = ""
        self._close()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Every keystroke narrows the pane at once."""
        event.stop()
        self.pane.set_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter: the filter stays, the pane gets the focus back."""
        event.stop()
        self._close()

    def on_blur(self) -> None:
        """Focus went elsewhere: same as a close."""
        self._close()

    def _close(self) -> None:
        """Back to the pane. The box stays in view only while it holds a filter."""
        self.display = bool(self.value)
        self.pane.focus()


class ProjectsPane(Filterable, OptionList):
    """The left pane: every project with a session, under one 'All projects' line."""

    BINDINGS = [
        *SHARED_BINDINGS,
        *FILTER_BINDINGS,
        Binding("enter", "select", "Sessions"),
    ]

    class Chosen(Message):
        """The highlight moved. ``path`` is None on the 'All projects' line."""

        def __init__(self, path: str | None) -> None:
            super().__init__()
            self.path = path

    class Opened(Message):
        """The user pressed enter on a project: they want to work on its sessions."""

    def __init__(self) -> None:
        super().__init__(id="projects")
        self.border_title = "Projects"
        self._projects: list[Project] = []
        self._selected: str | None = None

    @property
    def selected_path(self) -> str | None:
        """The path of the highlighted project, or None for 'All projects'."""
        return self._selected

    def show(self, projects: list[Project]) -> None:
        """Replace the list. The highlight stays on its project when it is still there."""
        self._projects = list(projects)
        self._rebuild()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Turn the widget's own message into one that names the project."""
        event.stop()
        self._selected = event.option_id
        self.post_message(self.Chosen(event.option_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on a project."""
        event.stop()
        self.post_message(self.Opened())

    def _rebuild(self) -> None:
        """Put the lines back, with the filter in effect.

        The highlight finds its project by path. When the project is gone, or
        filtered out, the highlight takes the line that replaced it.
        """
        wanted = self._selected
        index = self.highlighted or 0
        self.clear_options()
        self.add_option(Option(Content(ALL_PROJECTS), id=None))
        self.add_options(
            Option(Content(project.path), id=project.path)
            for project in self._projects
            if self._matches(project.path)
        )
        if wanted is None:
            index = 0
        else:
            try:
                index = self.get_option_index(wanted)
            except OptionDoesNotExist:
                index = min(index, self.option_count - 1)
        # ``clear_options`` dropped the highlight
        self.highlighted = index


class SessionsPane(Filterable, DataTable):
    """The upper right pane: the sessions of one project."""

    BINDINGS = [
        *SHARED_BINDINGS,
        *FILTER_BINDINGS,
        Binding("o", "sort_next", "Sort"),
        Binding("O", "sort_reverse", "Reverse"),
    ]

    class Chosen(Message):
        """The cursor moved to a session, or the table went empty (``None``)."""

        def __init__(self, session_id: str | None) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, fmt: Formatter) -> None:
        super().__init__(id="sessions", cursor_type="row")
        self.border_title = "Sessions"
        self.fmt = fmt
        self._sessions: list[Session] = []
        self._by_id: dict[str, Session] = {}
        self._with_project = False
        self._selected: str | None = None
        self._widths: tuple[int, int] = (0, 0)
        self._sort_column = "last_used"
        self._sort_descending = True

    @property
    def selected_id(self) -> str | None:
        """The id of the session under the cursor, or None when there is none."""
        return self._selected

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

    def show(self, sessions: list[Session], with_project: bool) -> None:
        """Replace the rows. The cursor stays on its session when it is still listed.

        The Project column is shown only when ``with_project`` is true, which
        is the 'All projects' view.
        """
        self._sessions = list(sessions)
        self._by_id = {session.id: session for session in self._sessions}
        self._with_project = with_project
        self._rebuild()

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
        """The o key: order by the next column along."""
        shown = self._shown_columns()
        try:
            index = shown.index(self._sort_column)
        except ValueError:
            index = -1
        self.sort_by(shown[(index + 1) % len(shown)])

    def action_sort_reverse(self) -> None:
        """The O key: the same column, the other way round."""
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

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Turn the widget's own message into one that names the session."""
        event.stop()
        self._select(event.row_key.value)

    def _select(self, session_id: str | None) -> None:
        self._selected = session_id
        self.post_message(self.Chosen(session_id))

    def _announce(self) -> None:
        """Say what the cursor sits on now, even when no row event will."""
        if not self.row_count:
            self._select(None)
            return
        cell = self.coordinate_to_cell_key(self.cursor_coordinate)
        self._select(cell.row_key.value)

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
            kept, key=sort_key(self._sort_column), reverse=self._sort_descending
        )

    def _fit(self) -> tuple[int, int]:
        """How wide the Title and Project columns can be with the room on hand."""
        labels = self._labels()
        padding = 2 * self.cell_padding
        times = [len(self.fmt.timestamp(s.last_used)) for s in self._sessions]
        sizes = [len(self.fmt.size(s.size)) for s in self._sessions]
        fixed = (
            max([len(labels["last_used"]), *times])
            + max([len(labels["size"]), *sizes])
            + len(labels["msgs"])
            + 3 * padding
        )
        room = self.size.width - SCROLLBAR_WIDTH - fixed
        if not self._with_project:
            return max(room - padding, NARROWEST_COLUMN), 0
        room -= 2 * padding
        title = max(int(room * TITLE_SHARE), NARROWEST_COLUMN)
        return title, max(room - title, NARROWEST_COLUMN)

    def _rebuild(self) -> None:
        """Put the rows back."""
        wanted = self._selected
        index = self.cursor_row
        labels = self._labels()
        self._widths = self._fit()
        title_width, project_width = self._widths
        self.clear(columns=True)
        self.add_column(labels["title"], key="title", width=title_width)
        self.add_column(labels["last_used"], key="last_used")
        self.add_column(Text(labels["size"], justify="right"), key="size")
        self.add_column(labels["msgs"], key="msgs")
        if self._with_project:
            self.add_column(labels["project"], key="project", width=project_width)
        for session in self._rows():
            cells: list[Text | str] = [
                Text(self.fmt.titled(session), no_wrap=True, overflow="ellipsis"),
                self.fmt.timestamp(session.last_used),
                Text(self.fmt.size(session.size), justify="right"),
                # Turn count: filled by a deep scan, which does not exist yet.
                "",
            ]
            if self._with_project:
                cells.append(
                    Text(session.project_path, no_wrap=True, overflow="ellipsis")
                )
            self.add_row(*cells, key=session.id)
        if self.row_count:
            if wanted is not None and self.rows.get(wanted) is not None:
                index = self.get_row_index(wanted)
            self.move_cursor(row=min(index, self.row_count - 1), animate=False)
        self._announce()


class DetailsPane(VerticalScroll):
    """The lower right pane: one session in full, the same lines ``info`` prints."""

    BINDINGS = [*SHARED_BINDINGS]

    def __init__(self, fmt: Formatter) -> None:
        super().__init__(id="details")
        self.border_title = "Details"
        self.fmt = fmt
        self.text = ""

    def compose(self) -> ComposeResult:
        """One block of text, scrolled by the pane around it."""
        yield Static(id="details-text", markup=False)

    def show(self, details: SessionDetails | None) -> None:
        """Show one session, or the empty state when there is none."""
        if details is None:
            self.text = "No session."
        else:
            lines = self.fmt.describe(details)
            width = max(len(label) for label, _ in lines) + 1
            self.text = "\n".join(
                f"{(label + ':').ljust(width)} {value}" for label, value in lines
            )
        self.query_one("#details-text", Static).update(self.text)
