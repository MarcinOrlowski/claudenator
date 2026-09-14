"""The things the store hands out. Plain data. Nothing in here touches the disk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _iso(value: datetime | None) -> str | None:
    """A timestamp for JSON output, to the second. Never microseconds."""
    return value.isoformat(timespec="seconds") if value else None


@dataclass(frozen=True)
class Session:
    """One Claude Code conversation, with every cheap field known about it."""

    id: str
    project_key: str
    project_path: str
    project_source: str
    title: str
    title_source: str
    transcript_path: Path
    transcript_size: int
    last_used: datetime
    created: datetime | None
    sidecar_path: Path | None
    sidecar_size: int
    subagent_count: int
    git_branch: str | None
    version: str | None
    fork_parent: str | None
    damaged: bool
    live: bool = False

    @property
    def size(self) -> int:
        """Bytes on disk, transcript plus sidecar. This is what a removal wins back."""
        return self.transcript_size + self.sidecar_size

    @property
    def is_fork(self) -> bool:
        """True when the session carries records copied from another session."""
        return self.fork_parent is not None

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for JSON output."""
        return {
            "id": self.id,
            "title": self.title,
            "title_source": self.title_source,
            "project_path": self.project_path,
            "project_source": self.project_source,
            "project_key": self.project_key,
            "created": _iso(self.created),
            "last_used": _iso(self.last_used),
            "size": self.size,
            "transcript_size": self.transcript_size,
            "sidecar_size": self.sidecar_size,
            "subagent_count": self.subagent_count,
            "git_branch": self.git_branch,
            "version": self.version,
            "fork_parent": self.fork_parent,
            "damaged": self.damaged,
            "live": self.live,
            "transcript_path": str(self.transcript_path),
            "sidecar_path": str(self.sidecar_path) if self.sidecar_path else None,
        }


@dataclass(frozen=True)
class SessionDetails:
    """One session in full, plus the one number that needs the whole transcript read."""

    session: Session
    inherited_bytes: int

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for JSON output."""
        data = self.session.to_dict()
        data["inherited_bytes"] = self.inherited_bytes
        return data


@dataclass(frozen=True)
class Project:
    """A working directory Claude Code was started in, with the sessions it owns.

    Grouped by the real path, never by the stored folder name. Two paths that
    collide onto one folder name are two projects.
    """

    path: str
    keys: tuple[str, ...]
    sessions: tuple[Session, ...]

    @property
    def size(self) -> int:
        """Bytes on disk across every session of the project."""
        return sum(session.size for session in self.sessions)

    @property
    def last_used(self) -> datetime | None:
        """When any session of the project was last used."""
        if not self.sessions:
            return None
        return max(session.last_used for session in self.sessions)

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for JSON output."""
        return {
            "path": self.path,
            "keys": list(self.keys),
            "session_count": len(self.sessions),
            "size": self.size,
            "last_used": _iso(self.last_used),
        }
