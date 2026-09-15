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

from pathlib import Path


class ClaudenatorError(Exception):
    """Base for every error."""


class SessionNotFound(ClaudenatorError):
    """No session matches the id, or the prefix of an id."""

    def __init__(self, wanted: str) -> None:
        super().__init__(f"no session matches '{wanted}'")
        self.wanted = wanted


class AmbiguousSessionId(ClaudenatorError):
    """A prefix matches more than one session."""

    def __init__(self, wanted: str, candidates: list[str]) -> None:
        shown = ", ".join(candidate[:8] for candidate in sorted(candidates))
        super().__init__(f"'{wanted}' matches {len(candidates)} sessions: {shown}")
        self.wanted = wanted
        self.candidates = candidates


class SessionIsLive(ClaudenatorError):
    """A process is running the session right now."""

    def __init__(self, session_id: str, pid: int) -> None:
        super().__init__(
            f"session {session_id[:8]} is live (pid {pid}) and cannot be trashed"
        )
        self.session_id = session_id
        self.pid = pid


class TrashFailed(ClaudenatorError):
    """A part of a session could not be moved."""

    def __init__(self, session_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not move {path}: {cause.strerror or cause}")
        self.session_id = session_id
        self.path = path
        self.cause = cause


class TrashEntryNotFound(ClaudenatorError):
    """No Trash entry matches the id, or the prefix of an id."""

    def __init__(self, wanted: str) -> None:
        super().__init__(f"no Trash entry matches '{wanted}'")
        self.wanted = wanted


class AmbiguousTrashEntry(ClaudenatorError):
    """A prefix matches more than one Trash entry."""

    def __init__(self, wanted: str, candidates: list[str]) -> None:
        shown = ", ".join(sorted(candidates))
        super().__init__(f"'{wanted}' matches {len(candidates)} Trash entries: {shown}")
        self.wanted = wanted
        self.candidates = candidates


class TrashEntryDamaged(ClaudenatorError):
    """The entry cannot be restored as it is."""

    def __init__(self, entry_id: str, path: Path, why: str) -> None:
        super().__init__(f"Trash entry {entry_id} is damaged: {why}: {path}")
        self.entry_id = entry_id
        self.path = path
        self.why = why


class RestoreClash(ClaudenatorError):
    """Something already sits where a part must go back."""

    def __init__(self, entry_id: str, path: Path) -> None:
        super().__init__(f"cannot restore {entry_id}: {path} is in the way")
        self.entry_id = entry_id
        self.path = path


class RestoreFailed(ClaudenatorError):
    """A part could not be moved back."""

    def __init__(self, entry_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not restore {path}: {cause.strerror or cause}")
        self.entry_id = entry_id
        self.path = path
        self.cause = cause


class ScanFailed(ClaudenatorError):
    """A transcript could not be read to its end."""

    def __init__(self, session_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not read {path}: {cause.strerror or cause}")
        self.session_id = session_id
        self.path = path
        self.cause = cause


class CacheDamaged(ClaudenatorError):
    """The cache file is not a database the tool can use. Remove it and scan again."""

    def __init__(self, path: Path, cause: Exception) -> None:
        super().__init__(
            f"the cache {path} is damaged ({cause}); remove it and scan again"
        )
        self.path = path
        self.cause = cause


class PurgeFailed(ClaudenatorError):
    """An entry could not be removed from the disk."""

    def __init__(self, entry_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not remove {path}: {cause.strerror or cause}")
        self.entry_id = entry_id
        self.path = path
        self.cause = cause
