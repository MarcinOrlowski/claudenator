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

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen, ScreenResultType
from textual.widget import Widget
from textual.widgets import Footer, Header

from conclaude import __title__
from conclaude.core.errors import ConclaudeError
from conclaude.core.format import Formatter
from conclaude.core.model import Session, SessionDetails, TrashEntry
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore, projects_of
from conclaude.tui.about import AboutScreen
from conclaude.tui.panes import (
    DaysPane,
    DetailsPane,
    EntriesPane,
    EntryPane,
    FilterBox,
    FilterWanted,
    Lines,
    ProjectsPane,
    SessionsPane,
    Table,
    TooSmall,
)


@dataclass(frozen=True)
class TrashVisit:
    """What a stay in Trash mode hands back when the panes switch to the sessions."""

    entries: list[TrashEntry]
    restored: list[Session]


class FullScreen(ModalScreen[None]):
    """One session, or one Trash entry, in full over the whole window.

    A small pane cuts a long line to fit. This box gives the same lines the
    whole window. The arrow keys scroll it, and escape closes it.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(
        self, title: str, fmt: Formatter, lines: list[tuple[str, str]]
    ) -> None:
        super().__init__()
        self.box_title = title
        self.fmt = fmt
        self.lines = lines

    def compose(self) -> ComposeResult:
        yield Lines("full", self.box_title, self.fmt, "")
        yield Footer()

    def on_mount(self) -> None:
        """The lines go in, and the box takes the focus so the keys scroll it."""
        pane = self.query_one(Lines)
        pane.show_lines(self.lines)
        pane.focus()

    def action_close(self) -> None:
        """The box goes, and the pane that opened it has the focus again."""
        self.dismiss(None)


class PaneScreen(Screen[ScreenResultType]):
    """Three panes under the header"""

    def __init__(self, store: SessionStore, fmt: Formatter) -> None:
        super().__init__()
        self.store = store
        self.fmt = fmt

    def on_filter_wanted(self, event: FilterWanted) -> None:
        """A pane asked for its filter box."""
        box = self.query_one(f"#{event.pane.id}-filter", FilterBox)
        if event.clear:
            box.action_cancel()
        else:
            box.open()

    def on_resize(self) -> None:
        """The window has another size: fit the panes to it."""
        self._fit_window()

    def _too_small(self) -> TooSmall:
        """The message that takes the place of the panes, sized from the settings."""
        settings = self.store.settings
        return TooSmall(settings.min_width, settings.min_height)

    def _size_left(self, stacked: bool) -> None:
        """Size the left pane from the settings, for the layout in effect.

        Side by side, it takes a share of the width, between the two limits the
        settings give. In one column, it takes the same share of the height,
        never below the limit the settings give, and the full width.
        """
        settings = self.store.settings
        share = f"{settings.projects_pane_share:.0%}"
        left = self.query_one("#left")
        if stacked:
            left.styles.width = "1fr"
            left.styles.min_width = 0
            left.styles.max_width = "100%"
            left.styles.height = share
            left.styles.min_height = settings.projects_pane_min_height
        else:
            left.styles.width = share
            left.styles.min_width = settings.projects_pane_min_width
            left.styles.max_width = settings.projects_pane_max_width
            left.styles.height = "1fr"
            left.styles.min_height = 0

    def _fit_window(self) -> None:
        """Give the layout the shape the window has room for.

        A narrow window puts the panes in one column, one over the other, so
        that every one of them keeps the full width. No pane ever goes out of
        view on its own. Under the smallest window that works, a plain message
        takes the place of them all. Every width comes from the settings
        object, and no step is one way: the layout goes back as the window grows.
        """
        settings = self.store.settings
        width, height = self.size
        too_small = width < settings.min_width or height < settings.min_height
        stacked = width < settings.stack_panes_below
        body = self.query_one("#body")
        body.display = not too_small
        body.set_class(stacked, "-stacked")
        self.query_one(TooSmall).display = too_small
        self._size_left(stacked)
        self._keep_focus()

    def _keep_focus(self) -> None:
        """Hold the focus on a pane through every change of size.

        A window with no room for the panes takes them out of view, and the
        library drops the focus with them. The keys of the pane go too, and a
        window that answers no key at all would trap the user. So the table
        takes the focus back: it is the pane the user works in.
        """
        focused = self.focused
        if focused is not None and all(
            node.display
            for node in focused.ancestors_with_self
            if isinstance(node, Widget)
        ):
            return
        self.query_one(Table).focus()

    def _show_trash_total(self, entries: list[TrashEntry]) -> None:
        """The header says what the Trash holds now."""
        self.app.sub_title = self.fmt.trash_line(entries)


class MainScreen(PaneScreen[None]):
    """The projects, the sessions of one of them, and one session in full."""

    def __init__(self, store: SessionStore, fmt: Formatter) -> None:
        super().__init__(store, fmt)
        self._sessions: list[Session] = []
        self._by_id: dict[str, Session] = {}
        self._details: dict[str, SessionDetails] = {}
        self._trash: list[TrashEntry] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="left"):
                projects = ProjectsPane(self.fmt)
                yield projects
                yield FilterBox(projects)
            with Vertical(id="right"):
                sessions = SessionsPane(self.fmt)
                yield sessions
                yield FilterBox(sessions)
                yield DetailsPane(self.fmt)
        yield self._too_small()
        yield Footer()

    def on_mount(self) -> None:
        """Shape the layout and order the table from the settings, fill and focus."""
        settings = self.store.settings
        self._fit_window()
        self.query_one(SessionsPane).sort_by(
            settings.sort_column, settings.sort_descending
        )
        self.load()
        self.query_one(ProjectsPane).focus()

    def load(self) -> None:
        """Read every session and the Trash again, and fill the panes."""
        self.store.reload()
        self._sessions = self.store.list_sessions()
        self._by_id = {session.id: session for session in self._sessions}
        self._details.clear()
        self._trash = self.store.list_trash()
        self._show_trash_total(self._trash)
        self.query_one(ProjectsPane).show(projects_of(self._sessions))

    def action_reload(self) -> None:
        """Pseudo-global ``r`` key on any pane."""
        self.load()

    def action_trash_mode(self) -> None:
        """The t key: the panes switch to the Trash."""
        self.app.push_screen(TrashScreen(self.store, self.fmt), self._back_from_trash)

    def on_projects_pane_chosen(self, event: ProjectsPane.Chosen) -> None:
        """List sessions of highlighted project."""
        if event.path is None:
            shown = self._sessions
        else:
            shown = [s for s in self._sessions if s.project_path == event.path]
        self.query_one(SessionsPane).show(shown, with_project=event.path is None)

    def on_projects_pane_opened(self) -> None:
        """Enter on a project moves the user into its sessions."""
        self.query_one(SessionsPane).focus()

    def on_sessions_pane_chosen(self, event: SessionsPane.Chosen) -> None:
        """The cursor sits on a session."""
        session = self._by_id.get(event.session_id) if event.session_id else None
        self.query_one(DetailsPane).show(self._details_of(session))

    def on_sessions_pane_opened(self, event: SessionsPane.Opened) -> None:
        """Enter on a session: its details take the whole window.

        This is the way to the details in a window too narrow to hold the pane.
        """
        details = self._details_of(event.session)
        if details is not None:
            self.app.push_screen(
                FullScreen("Details", self.fmt, self.fmt.describe(details))
            )

    def on_sessions_pane_trash_wanted(self, event: SessionsPane.TrashWanted) -> None:
        """The d key: the session goes to the Trash and its row goes from the table.

        Nothing reloads. A session that will not go, a live one for instance,
        stays where it is and the reason shows in a notification.
        """
        session = event.session
        try:
            entry = self.store.trash_of(session)
        except ConclaudeError as error:
            self.notify(str(error), title="Not trashed", severity="error")
            return
        self._trash.insert(0, entry)
        self._show_trash_total(self._trash)
        self._forget(session)

    def _back_from_trash(self, visit: TrashVisit | None) -> None:
        """The panes are back from the Trash."""
        if visit is None:
            return
        self._trash = visit.entries
        self._show_trash_total(self._trash)
        if not visit.restored:
            return
        for session in visit.restored:
            self._by_id[session.id] = session
        self._sessions = list(self._by_id.values())
        self.query_one(ProjectsPane).show(projects_of(self._sessions))

    def _forget(self, session: Session) -> None:
        """Take one session off the screen, in place.

        When it was the last session of its project, the project goes from the
        projects pane too, and the highlight there takes the line that replaced it.
        """
        self._sessions = [s for s in self._sessions if s.id != session.id]
        self._by_id.pop(session.id, None)
        self._details.pop(session.id, None)
        self.query_one(SessionsPane).drop(session.id)
        if not any(s.project_path == session.project_path for s in self._sessions):
            self.query_one(ProjectsPane).show(projects_of(self._sessions))

    def _details_of(self, session: Session | None) -> SessionDetails | None:
        """The session details."""
        if session is None:
            return None
        found = self._details.get(session.id)
        if found is None:
            found = self.store.details_of(session)
            self._details[session.id] = found
        return found


class TrashScreen(PaneScreen[TrashVisit]):
    """Trash mode: the days, the entries of one of them, and one entry in full."""

    def __init__(self, store: SessionStore, fmt: Formatter) -> None:
        super().__init__(store, fmt)
        self._entries: list[TrashEntry] = []
        self._by_id: dict[str, TrashEntry] = {}
        self._restored: list[Session] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield DaysPane(self.fmt)
            with Vertical(id="right"):
                entries = EntriesPane(self.fmt)
                yield entries
                yield FilterBox(entries)
                yield EntryPane(self.fmt)
        yield self._too_small()
        yield Footer()

    def on_mount(self) -> None:
        """Shape the layout, fill, and focus the entries: that is where the keys are."""
        self._fit_window()
        self.load()
        self.query_one(EntriesPane).focus()

    def load(self) -> None:
        """Read the Trash again and fill the panes."""
        self._entries = self.store.list_trash()
        self._by_id = {entry.id: entry for entry in self._entries}
        self._show_trash_total(self._entries)
        self.query_one(DaysPane).show(self._entries)

    def action_reload(self) -> None:
        """Pseudo-global ``r`` key on any pane."""
        self.load()

    def action_sessions_mode(self) -> None:
        """The t key: the panes switch back to the sessions."""
        self.dismiss(TrashVisit(self._entries, self._restored))

    def on_days_pane_chosen(self, event: DaysPane.Chosen) -> None:
        """List the entries that went in on the highlighted day."""
        if event.day is None:
            shown = self._entries
        else:
            shown = [
                e for e in self._entries if self.fmt.day(e.trashed_at) == event.day
            ]
        self.query_one(EntriesPane).show(shown)

    def on_days_pane_opened(self) -> None:
        """Enter on a day moves the user into its entries."""
        self.query_one(EntriesPane).focus()

    def on_entries_pane_chosen(self, event: EntriesPane.Chosen) -> None:
        """The cursor sits on an entry."""
        entry = self._by_id.get(event.entry_id) if event.entry_id else None
        self.query_one(EntryPane).show(entry)

    def on_entries_pane_opened(self, event: EntriesPane.Opened) -> None:
        """Enter on an entry: it takes the whole window, pane or no pane."""
        self.app.push_screen(
            FullScreen("Entry", self.fmt, self.fmt.describe_entry(event.entry))
        )

    def on_entries_pane_restore_wanted(self, event: EntriesPane.RestoreWanted) -> None:
        """The ``u`` key: the entry goes back."""
        entry = event.entry
        try:
            self.store.restore_of(entry)
        except ConclaudeError as error:
            self.notify(str(error), title="Not restored", severity="error")
            return
        session = self.store.session_of(entry)
        if session is not None:
            self._restored.append(session)
        self._forget(entry)

    def on_entries_pane_purge_wanted(self, event: EntriesPane.PurgeWanted) -> None:
        """The ``x`` key: the entry is gone for good."""
        entry = event.entry
        try:
            self.store.purge_of(entry)
        except ConclaudeError as error:
            self.notify(str(error), title="Not purged", severity="error")
            return
        self._forget(entry)

    def _forget(self, entry: TrashEntry) -> None:
        """Take one entry off the screen"""
        self._entries = [e for e in self._entries if e.id != entry.id]
        self._by_id.pop(entry.id, None)
        self._show_trash_total(self._entries)
        self.query_one(EntriesPane).drop(entry.id)
        day = self.fmt.day(entry.trashed_at)
        if not any(self.fmt.day(e.trashed_at) == day for e in self._entries):
            self.query_one(DaysPane).show(self._entries)


class ConclaudeApp(App[None]):
    """The TUI"""

    TITLE = __title__
    CSS_PATH = "conclaude.tcss"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings if settings is not None else Settings()
        self.store = SessionStore(self.settings)
        self.fmt = Formatter(self.settings)

    def get_default_screen(self) -> MainScreen:
        """The screen shown at start."""
        return MainScreen(self.store, self.fmt)

    def action_about(self) -> None:
        """The ``?`` key on any pane: the About box opens over the panes."""
        self.push_screen(AboutScreen())

    def on_mount(self) -> None:
        """The theme in effect is the one the settings name."""
        self.theme = self.settings.theme


def run(settings: Settings | None = None) -> int:
    """Open the screen and return when the user quits. Returns the exit code."""
    ConclaudeApp(settings).run()
    return 0
