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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _iso(value: datetime | None) -> str | None:
    """A timestamp for JSON output, to the second. Never microseconds."""
    return value.isoformat(timespec="seconds") if value else None


@dataclass(frozen=True)
class Figures:
    """The costly numbers of one session: what a read of the whole transcript found.

    The transcript's size and change time say which copy of the file the
    numbers describe. ``stale`` is True when the file has changed since, so
    the numbers are old but still worth a look.
    """

    transcript_path: Path
    transcript_size: int
    transcript_mtime_ns: int
    scanned_at: datetime
    turns: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    # Model name and the messages it answered, most used first.
    models: tuple[tuple[str, int], ...]
    # Tool name and how many times it was called, most called first.
    tools: tuple[tuple[str, int], ...]
    first_at: datetime | None
    last_at: datetime | None
    stale: bool = False

    @property
    def tokens(self) -> int:
        """Every token, in and out, cached or not."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    @property
    def tool_calls(self) -> int:
        """How many times any tool was called."""
        return sum(count for _name, count in self.tools)

    @property
    def duration(self) -> timedelta | None:
        """From the first record with a time to the last one. None with no times."""
        if self.first_at is None or self.last_at is None:
            return None
        return self.last_at - self.first_at

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for JSON output."""
        duration = self.duration
        return {
            "scanned_at": _iso(self.scanned_at),
            "stale": self.stale,
            "turns": self.turns,
            "tokens": self.tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "models": dict(self.models),
            "tool_calls": self.tool_calls,
            "tools": dict(self.tools),
            "first_at": _iso(self.first_at),
            "last_at": _iso(self.last_at),
            "duration_seconds": (
                int(duration.total_seconds()) if duration is not None else None
            ),
        }


@dataclass(frozen=True)
class Session:
    """Single Claude Code conversation"""

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
    pid: int | None = None

    @property
    def size(self) -> int:
        """Bytes on disk, transcript plus sidecar."""
        return self.transcript_size + self.sidecar_size

    @property
    def is_fork(self) -> bool:
        """True when the session waas forked from another session."""
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
            "pid": self.pid,
            "transcript_path": str(self.transcript_path),
            "sidecar_path": str(self.sidecar_path) if self.sidecar_path else None,
        }


@dataclass(frozen=True)
class SessionDetails:
    """One session in full, plus the numbers that need the whole transcript read.

    ``figures`` come from the cache alone. None means no deep scan has run yet.
    """

    session: Session
    inherited_bytes: int
    figures: Figures | None = None

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for JSON output."""
        data = self.session.to_dict()
        data["inherited_bytes"] = self.inherited_bytes
        data["figures"] = self.figures.to_dict() if self.figures else None
        return data


@dataclass(frozen=True)
class Part:
    """One piece of a session.

    ``original`` is the absolute path the part lives at under Claude Code's
    folder. ``stored`` is where it sits inside a Trash entry, relative to the
    entry folder.
    """

    kind: str
    original: Path
    stored: Path
    is_dir: bool
    size: int

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for the manifest and for JSON output."""
        return {
            "kind": self.kind,
            "original": str(self.original),
            "stored": str(self.stored),
            "type": "dir" if self.is_dir else "file",
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Part:
        """A part read back from a manifest. Raises ``ValueError`` for a bad record."""
        if not isinstance(data, dict):
            raise ValueError("a part must be an object")
        kind = data.get("kind")
        original = data.get("original")
        stored = data.get("stored")
        shape = data.get("type")
        size = data.get("size")
        if not (
            isinstance(kind, str)
            and isinstance(original, str)
            and isinstance(stored, str)
            and shape in ("dir", "file")
            and isinstance(size, int)
            and not isinstance(size, bool)
        ):
            raise ValueError("a part record is missing a field or has a wrong one")
        return cls(
            kind=kind,
            original=Path(original),
            stored=Path(stored),
            is_dir=shape == "dir",
            size=size,
        )


@dataclass(frozen=True)
class TrashEntry:
    """One act of trashing: one session, every part of it, in one folder.

    ``id`` is the name of the entry folder.
    """

    id: str
    path: Path
    session_id: str
    trashed_at: datetime
    reason: str | None
    title: str
    project_path: str
    parts: tuple[Part, ...]

    @property
    def size(self) -> int:
        """Bytes the entry holds, over every part."""
        return sum(part.size for part in self.parts)

    def to_dict(self) -> dict[str, Any]:
        """A plain dict for JSON output."""
        return {
            "id": self.id,
            "path": str(self.path),
            "session_id": self.session_id,
            "trashed_at": _iso(self.trashed_at),
            "reason": self.reason,
            "title": self.title,
            "project_path": self.project_path,
            "size": self.size,
            "parts": [part.to_dict() for part in self.parts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path) -> TrashEntry:
        """An entry read back from the manifest in its folder.

        The folder name is the id. Raises ``ValueError`` for a record that
        is missing a field or has a wrong one.
        """
        session_id = data.get("session_id")
        trashed_at = data.get("trashed_at")
        reason = data.get("reason")
        title = data.get("title")
        project_path = data.get("project_path")
        parts = data.get("parts")
        if not (
            isinstance(session_id, str)
            and isinstance(trashed_at, str)
            and (reason is None or isinstance(reason, str))
            and isinstance(title, str)
            and isinstance(project_path, str)
            and isinstance(parts, list)
        ):
            raise ValueError("the manifest is missing a field or has a wrong one")
        moment = datetime.fromisoformat(trashed_at)
        if moment.tzinfo is None:
            moment = moment.astimezone()
        return cls(
            id=path.name,
            path=path,
            session_id=session_id,
            trashed_at=moment,
            reason=reason,
            title=title,
            project_path=project_path,
            parts=tuple(Part.from_dict(part) for part in parts),
        )


@dataclass(frozen=True)
class Project:
    """A working directory Claude Code was started in, with the sessions it owns.

    Grouped by real path. Two paths that collide onto one name are two projects.
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
