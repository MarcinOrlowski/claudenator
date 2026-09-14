"""The errors the core layer raises on purpose. All of them share one base."""

from __future__ import annotations

from pathlib import Path


class ConclaudeError(Exception):
    """Base for every error."""


class SessionNotFound(ConclaudeError):
    """No session matches the id, or the prefix of an id."""

    def __init__(self, wanted: str) -> None:
        super().__init__(f"no session matches '{wanted}'")
        self.wanted = wanted


class AmbiguousSessionId(ConclaudeError):
    """A prefix matches more than one session."""

    def __init__(self, wanted: str, candidates: list[str]) -> None:
        shown = ", ".join(candidate[:8] for candidate in sorted(candidates))
        super().__init__(f"'{wanted}' matches {len(candidates)} sessions: {shown}")
        self.wanted = wanted
        self.candidates = candidates


class SessionIsLive(ConclaudeError):
    """A process is running the session right now."""

    def __init__(self, session_id: str, pid: int) -> None:
        super().__init__(
            f"session {session_id[:8]} is live (pid {pid}) and cannot be trashed"
        )
        self.session_id = session_id
        self.pid = pid


class TrashFailed(ConclaudeError):
    """A part of a session could not be moved."""

    def __init__(self, session_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not move {path}: {cause.strerror or cause}")
        self.session_id = session_id
        self.path = path
        self.cause = cause


class TrashEntryNotFound(ConclaudeError):
    """No Trash entry matches the id, or the prefix of an id."""

    def __init__(self, wanted: str) -> None:
        super().__init__(f"no Trash entry matches '{wanted}'")
        self.wanted = wanted


class AmbiguousTrashEntry(ConclaudeError):
    """A prefix matches more than one Trash entry."""

    def __init__(self, wanted: str, candidates: list[str]) -> None:
        shown = ", ".join(sorted(candidates))
        super().__init__(f"'{wanted}' matches {len(candidates)} Trash entries: {shown}")
        self.wanted = wanted
        self.candidates = candidates


class TrashEntryDamaged(ConclaudeError):
    """The entry cannot be restored as it is."""

    def __init__(self, entry_id: str, path: Path, why: str) -> None:
        super().__init__(f"Trash entry {entry_id} is damaged: {why}: {path}")
        self.entry_id = entry_id
        self.path = path
        self.why = why


class RestoreClash(ConclaudeError):
    """Something already sits where a part must go back."""

    def __init__(self, entry_id: str, path: Path) -> None:
        super().__init__(f"cannot restore {entry_id}: {path} is in the way")
        self.entry_id = entry_id
        self.path = path


class RestoreFailed(ConclaudeError):
    """A part could not be moved back."""

    def __init__(self, entry_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not restore {path}: {cause.strerror or cause}")
        self.entry_id = entry_id
        self.path = path
        self.cause = cause


class PurgeFailed(ConclaudeError):
    """An entry could not be removed from the disk."""

    def __init__(self, entry_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not remove {path}: {cause.strerror or cause}")
        self.entry_id = entry_id
        self.path = path
        self.cause = cause
