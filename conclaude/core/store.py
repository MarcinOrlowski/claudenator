"""The session store: the only thing that reads or changes session data.

Everything else, the screen and the command line alike, asks this object.
Nothing else opens a transcript or touches a folder under Claude Code's data
directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from conclaude.core.errors import AmbiguousSessionId, SessionNotFound
from conclaude.core.live import LiveSession, find_live
from conclaude.core.model import Project, Session, SessionDetails
from conclaude.core.scan import (
    CheapFields,
    count_subagents,
    derive_title,
    folder_size,
    inherited_bytes,
    iter_project_dirs,
    iter_transcripts,
    read_cheap,
    sidecar_for,
)
from conclaude.core.settings import Settings


class SessionStore:
    """Every session on this machine, seen as one collection."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self._history: dict[str, str] | None = None

    def reload(self) -> None:
        """Forget anything remembered from the disk, so the next call reads afresh."""
        self._history = None

    def list_sessions(self) -> list[Session]:
        """Every session, sorted the way the settings say.

        Liveness is checked afresh on every call. It is a handful of small
        files and a process table, so it is cheap, and it must never be stale.
        """
        live = find_live(self.settings)
        sessions: list[Session] = []
        for project_dir in iter_project_dirs(self.settings.projects_dir):
            for session_id, transcript in iter_transcripts(project_dir):
                session = self._load(
                    project_dir.name, session_id, transcript, live.get(session_id)
                )
                if session is not None:
                    sessions.append(session)
        sessions.sort(key=self._sort_key(), reverse=self.settings.sort_descending)
        return sessions

    def list_projects(self) -> list[Project]:
        """Every project that still has a session, grouped by real path."""
        groups: dict[str, list[Session]] = {}
        for session in self.list_sessions():
            groups.setdefault(session.project_path, []).append(session)
        projects = [
            Project(
                path=path,
                keys=tuple(sorted({session.project_key for session in sessions})),
                sessions=tuple(sessions),
            )
            for path, sessions in groups.items()
        ]
        projects.sort(key=lambda project: project.path)
        return projects

    def get_session(self, session_id: str) -> Session | None:
        """One session by its full id, or None."""
        for session in self.list_sessions():
            if session.id == session_id:
                return session
        return None

    def find_session(self, wanted: str) -> Session:
        """One session by its full id or a unique prefix of it.

        Raises ``SessionNotFound`` or ``AmbiguousSessionId``. The tool never
        guesses between two sessions.
        """
        sessions = self.list_sessions()
        for session in sessions:
            if session.id == wanted:
                return session
        matches = [session for session in sessions if session.id.startswith(wanted)]
        if not matches:
            raise SessionNotFound(wanted)
        if len(matches) > 1:
            raise AmbiguousSessionId(wanted, [session.id for session in matches])
        return matches[0]

    def details(self, wanted: str) -> SessionDetails:
        """One session in full. For a fork, this reads the whole transcript once."""
        session = self.find_session(wanted)
        inherited = 0
        if session.is_fork:
            inherited = inherited_bytes(session.transcript_path, session.id)
        return SessionDetails(session=session, inherited_bytes=inherited)

    def _load(
        self,
        project_key: str,
        session_id: str,
        transcript: Path,
        live: LiveSession | None,
    ) -> Session | None:
        try:
            stat = transcript.stat()
        except OSError:
            return None
        fields = read_cheap(transcript, session_id, self.settings)
        sidecar = sidecar_for(transcript)
        title, title_source = derive_title(
            fields,
            session_id,
            self.settings.title_max_length,
            live.name if live else None,
        )
        project_path, project_source = self._resolve_project(
            project_key, session_id, fields
        )
        return Session(
            id=session_id,
            project_key=project_key,
            project_path=project_path,
            project_source=project_source,
            title=title,
            title_source=title_source,
            transcript_path=transcript,
            transcript_size=stat.st_size,
            last_used=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            created=fields.created,
            sidecar_path=sidecar,
            sidecar_size=folder_size(sidecar) if sidecar else 0,
            subagent_count=count_subagents(sidecar),
            git_branch=fields.git_branch,
            version=fields.version,
            fork_parent=fields.fork_parent,
            damaged=fields.damaged,
            live=live is not None,
            pid=live.pid if live else None,
        )

    def _resolve_project(
        self, project_key: str, session_id: str, fields: CheapFields
    ) -> tuple[str, str]:
        """The real project path and where it came from.

        The stored folder name is the last resort and is used only as a label.
        It is never decoded back into a path: the encoding is lossy.
        """
        if fields.cwd:
            return fields.cwd, "transcript"
        from_history = self._history_projects().get(session_id)
        if from_history:
            return from_history, "history"
        return project_key, "label"

    def _history_projects(self) -> dict[str, str]:
        """Session id to project path, from Claude Code's prompt history. Read once."""
        if self._history is not None:
            return self._history
        found: dict[str, str] = {}
        try:
            with open(self.settings.history_file, "rb") as handle:
                for raw in handle:
                    try:
                        record = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    session_id = record.get("sessionId")
                    project = record.get("project")
                    if (
                        isinstance(session_id, str)
                        and isinstance(project, str)
                        and project
                    ):
                        found[session_id] = project
        except OSError:
            pass
        self._history = found
        return found

    def _sort_key(self) -> Callable[[Session], Any]:
        column = self.settings.sort_column
        if column == "title":
            return lambda session: session.title.lower()
        if column == "size":
            return lambda session: session.size
        if column == "project_path":
            return lambda session: session.project_path
        if column == "created":
            return lambda session: session.created or session.last_used
        return lambda session: session.last_used
