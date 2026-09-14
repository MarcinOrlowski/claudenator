"""The errors the core layer raises on purpose. All of them share one base."""

from __future__ import annotations

from pathlib import Path


class ConclaudeError(Exception):
    """Base for every error the core layer raises on purpose."""


class SessionNotFound(ConclaudeError):
    """No session matches the id, or the prefix of an id, that was asked for."""

    def __init__(self, wanted: str) -> None:
        super().__init__(f"no session matches '{wanted}'")
        self.wanted = wanted


class AmbiguousSessionId(ConclaudeError):
    """A prefix matches more than one session, so the tool will not guess."""

    def __init__(self, wanted: str, candidates: list[str]) -> None:
        shown = ", ".join(candidate[:8] for candidate in sorted(candidates))
        super().__init__(f"'{wanted}' matches {len(candidates)} sessions: {shown}")
        self.wanted = wanted
        self.candidates = candidates


class SessionIsLive(ConclaudeError):
    """A process is running the session right now, so it cannot be trashed."""

    def __init__(self, session_id: str, pid: int) -> None:
        super().__init__(
            f"session {session_id[:8]} is live (pid {pid}) and cannot be trashed"
        )
        self.session_id = session_id
        self.pid = pid


class TrashFailed(ConclaudeError):
    """A part of a session could not be moved. The path names what stopped it."""

    def __init__(self, session_id: str, path: Path, cause: OSError) -> None:
        super().__init__(f"could not move {path}: {cause.strerror or cause}")
        self.session_id = session_id
        self.path = path
        self.cause = cause
