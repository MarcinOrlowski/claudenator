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
from textual.widgets import DataTable, OptionList, Static
from textual.widgets.option_list import Option, OptionDoesNotExist

from conclaude.core.format import Formatter
from conclaude.core.model import Project, Session, SessionDetails

# The keys every pane uses
SHARED_BINDINGS = [
    Binding("tab", "app.focus_next", "Next pane"),
    Binding("shift+tab", "app.focus_previous", "Previous pane", show=False),
    Binding("q", "app.quit", "Quit"),
]

ALL_PROJECTS = "All projects"

# Room kept for the vertical scrollbar of the sessions table.
SCROLLBAR_WIDTH = 2

# A flexible column is never squeezed below this limit.
NARROWEST_COLUMN = 12

# In the 'All projects' view the Title and Project columns share the room
# that the fixed columns leave. This is the Title column's part of it.
TITLE_SHARE = 0.6


class ProjectsPane(OptionList):
    """The left pane: every project with a session, under one 'All projects' line."""

    BINDINGS = [
        *SHARED_BINDINGS,
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
        self._selected: str | None = None

    @property
    def selected_path(self) -> str | None:
        """The path of the highlighted project, or None for 'All projects'."""
        return self._selected

    def show(self, projects: list[Project]) -> None:
        """Replace the list. The highlight stays on its project when it is still there."""
        wanted = self._selected
        self.clear_options()
        self.add_option(Option(Content(ALL_PROJECTS), id=None))
        self.add_options(
            Option(Content(project.path), id=project.path) for project in projects
        )
        index = 0
        if wanted is not None:
            try:
                index = self.get_option_index(wanted)
            except OptionDoesNotExist:
                index = 0
        # ``clear_options`` dropped the highlight, so this always announces.
        self.highlighted = index

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


class SessionsPane(DataTable):
    """The upper right pane: the sessions of one project."""

    BINDINGS = [*SHARED_BINDINGS]

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

    def show(self, sessions: list[Session], with_project: bool) -> None:
        """Replace the rows. The cursor stays on its session when it is still listed.

        The Project column is shown only when ``with_project`` is true, which
        is the 'All projects' view.
        """
        self._sessions = list(sessions)
        self._by_id = {session.id: session for session in self._sessions}
        self._with_project = with_project
        self._rebuild()
        self._announce()

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

    def _fit(self) -> tuple[int, int]:
        """How wide the Title and Project columns can be with the room on hand."""
        padding = 2 * self.cell_padding
        times = [len(self.fmt.timestamp(s.last_used)) for s in self._sessions]
        sizes = [len(self.fmt.size(s.size)) for s in self._sessions]
        fixed = (
            max([len("Last used"), *times])
            + max([len("Size"), *sizes])
            + len("Msgs")
            + 3 * padding
        )
        room = self.size.width - SCROLLBAR_WIDTH - fixed
        if not self._with_project:
            return max(room - padding, NARROWEST_COLUMN), 0
        room -= 2 * padding
        title = max(int(room * TITLE_SHARE), NARROWEST_COLUMN)
        return title, max(room - title, NARROWEST_COLUMN)

    def _rebuild(self) -> None:
        wanted = self._selected
        self._widths = self._fit()
        title_width, project_width = self._widths
        self.clear(columns=True)
        self.add_column("Title", key="title", width=title_width)
        self.add_column("Last used", key="last_used")
        self.add_column(Text("Size", justify="right"), key="size")
        self.add_column("Msgs", key="msgs")
        if self._with_project:
            self.add_column("Project", key="project", width=project_width)
        for session in self._sessions:
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
        if wanted is not None and wanted in self._by_id:
            self.move_cursor(row=self.get_row_index(wanted), animate=False)


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
