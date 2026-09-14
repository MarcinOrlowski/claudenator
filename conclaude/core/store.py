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

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from conclaude.core.errors import (
    AmbiguousSessionId,
    AmbiguousTrashEntry,
    SessionNotFound,
    TrashEntryNotFound,
)
from conclaude.core.live import LiveSession, find_live
from conclaude.core.model import Project, Session, SessionDetails, TrashEntry
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
from conclaude.core.trash import (
    list_entries,
    purge_entry,
    restore_entry,
    total_size,
    trash_session,
)

# The columns a session list can be ordered by.
SORT_COLUMNS = ("title", "last_used", "created", "size", "msgs", "project")


def sort_key(column: str) -> Callable[[Session], Any]:
    """The key that orders sessions by ``column``. An unknown column orders by last use."""
    if column == "title":
        return lambda session: session.title.casefold()
    if column == "created":
        return lambda session: session.created or session.last_used
    if column == "size":
        return lambda session: session.size
    if column == "msgs":
        # Turn count: filled by a deep scan, which does not exist yet.
        return lambda _: 0
    if column == "project":
        return lambda session: session.project_path
    return lambda session: session.last_used


def projects_of(sessions: list[Session]) -> list[Project]:
    """The projects that own these sessions, grouped by real path, sorted by path."""
    groups: dict[str, list[Session]] = {}
    for session in sessions:
        groups.setdefault(session.project_path, []).append(session)
    projects = [
        Project(
            path=path,
            keys=tuple(sorted({session.project_key for session in found})),
            sessions=tuple(found),
        )
        for path, found in groups.items()
    ]
    projects.sort(key=lambda project: project.path)
    return projects


class SessionStore:
    """Every session on this machine, seen as one collection."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self._history: dict[str, str] | None = None

    def reload(self) -> None:
        """Forget anything remembered from the disk, so the next call reads afresh."""
        self._history = None

    def list_sessions(self) -> list[Session]:
        """Every session, sorted the way the settings say."""
        live = find_live(self.settings)
        sessions: list[Session] = []
        for project_dir in iter_project_dirs(self.settings.projects_dir):
            for session_id, transcript in iter_transcripts(project_dir):
                session = self._load(
                    project_dir.name, session_id, transcript, live.get(session_id)
                )
                if session is not None:
                    sessions.append(session)
        sessions.sort(
            key=sort_key(self.settings.sort_column),
            reverse=self.settings.sort_descending,
        )
        return sessions

    def list_projects(self) -> list[Project]:
        """Every project that still has a session, grouped by real path."""
        return projects_of(self.list_sessions())

    def get_session(self, session_id: str) -> Session | None:
        """One session by its full id, or None."""
        for session in self.list_sessions():
            if session.id == session_id:
                return session
        return None

    def find_session(self, wanted: str) -> Session:
        """One session by its full id or a unique prefix of it.

        Raises ``SessionNotFound`` or ``AmbiguousSessionId``.
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
        """One session in full, by its id or a unique prefix of it."""
        return self.details_of(self.find_session(wanted))

    def details_of(self, session: Session) -> SessionDetails:
        """One session in full. For a fork, this reads the whole transcript once."""
        inherited = 0
        if session.is_fork:
            inherited = inherited_bytes(session.transcript_path, session.id)
        return SessionDetails(session=session, inherited_bytes=inherited)

    def trash(self, wanted: str, reason: str | None = None) -> TrashEntry:
        """Move a session to the Trash, by its id or a unique prefix of it.

        Returns the entry that was made. Raises ``SessionIsLive`` for a session
        used by a running process.
        """
        return self.trash_of(self.find_session(wanted), reason)

    def trash_of(self, session: Session, reason: str | None = None) -> TrashEntry:
        """Move a session already in hand to the Trash. Nothing is read again.

        Returns the entry that was made. Raises ``SessionIsLive`` for a session
        used by a running process.
        """
        return trash_session(self.settings, session, reason)

    def list_trash(self) -> list[TrashEntry]:
        """Every entry in the Trash, newest first. Read afresh on every call."""
        return list_entries(self.settings)

    def trash_size(self) -> int:
        """Bytes the Trash holds, over every entry."""
        return total_size(self.settings)

    def find_entry(self, wanted: str) -> TrashEntry:
        """One Trash entry by its id, or by a unique prefix of its id or of its session id.

        Raises ``TrashEntryNotFound`` or ``AmbiguousTrashEntry``.
        """
        entries = self.list_trash()
        for entry in entries:
            if entry.id == wanted:
                return entry
        matches = [
            entry
            for entry in entries
            if entry.id.startswith(wanted) or entry.session_id.startswith(wanted)
        ]
        if not matches:
            raise TrashEntryNotFound(wanted)
        if len(matches) > 1:
            raise AmbiguousTrashEntry(wanted, [entry.id for entry in matches])
        return matches[0]

    def restore(self, wanted: str) -> TrashEntry:
        """Restores trashed entry. Returns the entry that was restored.

        Raises ``RestoreClash`` when something sits in target folder
        and ``TrashEntryDamaged`` when the entry cannot be restored.
        """
        return restore_entry(self.settings, self.find_entry(wanted))

    def purge(self, wanted: str) -> TrashEntry:
        """Remove one Trash entry from the disk for good. Returns what went."""
        return purge_entry(self.settings, self.find_entry(wanted))

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
        """The real project path and where it came from."""
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
