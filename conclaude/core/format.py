"""Turns moments, sizes and marks into text for a human.

One place, so the command line and the screen always agree. Every choice
comes from the settings object: how a time is shown (absolute, relative, or
both) and the pattern for the absolute form. JSON output does not pass
through here; it uses ISO 8601 to the second.
"""

from __future__ import annotations

from datetime import datetime, timezone

from conclaude.core.model import Session
from conclaude.core.settings import Settings

TIME_FORMATS = ("absolute", "relative", "both")
UNITS = (("y", 365 * 86400), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1))


class Formatter:
    """Text for a human, the way the settings ask for it."""

    def __init__(self, settings: Settings, now: datetime | None = None) -> None:
        if settings.time_format not in TIME_FORMATS:
            allowed = ", ".join(TIME_FORMATS)
            raise ValueError(
                f"time_format must be one of {allowed}, not '{settings.time_format}'"
            )
        self.settings = settings
        self._now = now

    def now(self) -> datetime:
        """The current moment. Fixed only when a test asked for it."""
        return self._now if self._now is not None else datetime.now(timezone.utc)

    def absolute(self, moment: datetime) -> str:
        """A moment in the user's own time zone, to the second."""
        return moment.astimezone().strftime(self.settings.time_pattern)

    def relative(self, moment: datetime) -> str:
        """How long ago a moment was: ``3d 23h ago``, ``45s ago``, ``just now``.

        The largest unit is shown, and the one below it when it is not zero.
        A moment in the future reads ``in 3m``.
        """
        seconds = int((self.now() - moment).total_seconds())
        future = seconds < 0
        seconds = abs(seconds)
        for index, (name, size) in enumerate(UNITS):
            if seconds < size:
                continue
            count, rest = divmod(seconds, size)
            text = f"{count}{name}"
            if index + 1 < len(UNITS):
                next_name, next_size = UNITS[index + 1]
                next_count = rest // next_size
                if next_count:
                    text = f"{text} {next_count}{next_name}"
            return f"in {text}" if future else f"{text} ago"
        return "just now"

    def timestamp(self, moment: datetime | None) -> str:
        """A moment, shown the way the settings say. ``-`` when there is none."""
        if moment is None:
            return "-"
        if self.settings.time_format == "relative":
            return self.relative(moment)
        if self.settings.time_format == "both":
            return f"{self.absolute(moment)} ({self.relative(moment)})"
        return self.absolute(moment)

    def size(self, size: int) -> str:
        """Bytes as a short string: ``12B``, ``3.4K``, ``1.2M``."""
        value = float(size)
        for unit in ("B", "K", "M", "G", "T"):
            if value < 1024 or unit == "T":
                if unit == "B":
                    return f"{int(value)}B"
                return f"{value:.1f}{unit}"
            value /= 1024
        return f"{int(value)}B"

    def marks(self, session: Session) -> str:
        """The small marks that sit on a title: live, fork, damaged."""
        parts = []
        if session.live:
            parts.append("[live]")
        if session.is_fork:
            parts.append("[fork]")
        if session.damaged:
            parts.append("[damaged]")
        return " ".join(parts)
