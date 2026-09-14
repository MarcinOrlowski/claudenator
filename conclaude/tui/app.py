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

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer

from conclaude.core.format import Formatter
from conclaude.core.model import Session, SessionDetails
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore, projects_of
from conclaude.tui.panes import DetailsPane, ProjectsPane, SessionsPane


class MainScreen(Screen[None]):
    """The three panes and the footer."""

    def __init__(self, store: SessionStore, fmt: Formatter) -> None:
        super().__init__()
        self.store = store
        self.fmt = fmt
        self._sessions: list[Session] = []
        self._by_id: dict[str, Session] = {}
        self._details: dict[str, SessionDetails] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            yield ProjectsPane()
            with Vertical(id="right"):
                yield SessionsPane(self.fmt)
                yield DetailsPane(self.fmt)
        yield Footer()

    def on_mount(self) -> None:
        """Size the projects pane from the settings, fill and focus."""
        settings = self.store.settings
        projects = self.query_one(ProjectsPane)
        projects.styles.width = f"{settings.projects_pane_share:.0%}"
        projects.styles.min_width = settings.projects_pane_min_width
        projects.styles.max_width = settings.projects_pane_max_width
        self.load()
        projects.focus()

    def load(self) -> None:
        """Read every session and fills the panes."""
        self._sessions = self.store.list_sessions()
        self._by_id = {session.id: session for session in self._sessions}
        self._details.clear()
        self.query_one(ProjectsPane).show(projects_of(self._sessions))

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

    def _details_of(self, session: Session | None) -> SessionDetails | None:
        """The session details."""
        if session is None:
            return None
        found = self._details.get(session.id)
        if found is None:
            found = self.store.details_of(session)
            self._details[session.id] = found
        return found


class ConclaudeApp(App[None]):
    """The TUI"""

    TITLE = "conclaude"
    CSS_PATH = "conclaude.tcss"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings if settings is not None else Settings()
        self.store = SessionStore(self.settings)
        self.fmt = Formatter(self.settings)

    def get_default_screen(self) -> MainScreen:
        """The screen shown at start."""
        return MainScreen(self.store, self.fmt)

    def on_mount(self) -> None:
        """The theme in effect is the one the settings name."""
        self.theme = self.settings.theme


def run(settings: Settings | None = None) -> int:
    """Open the screen and return when the user quits. Returns the exit code."""
    ConclaudeApp(settings).run()
    return 0
