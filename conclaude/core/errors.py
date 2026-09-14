"""The errors the core layer raises on purpose. All of them share one base."""

from __future__ import annotations


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
