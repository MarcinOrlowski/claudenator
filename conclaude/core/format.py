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

from collections.abc import Sequence
from datetime import datetime, timezone

from conclaude.core.model import Session, SessionDetails, TrashEntry
from conclaude.core.settings import Settings

TIME_FORMATS = ("absolute", "relative", "both")
UNITS = (("y", 365 * 86400), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
SEP = "/"


def parts_that_fit(parts: Sequence[str], room: int) -> int:
    """How many of ``parts``, joined with slashes from the first one, fit in ``room``."""
    count = used = 0
    for part in parts:
        need = len(part) + (len(SEP) if count else 0)
        if used + need > room:
            break
        used += need
        count += 1
    return count


class Formatter:
    """Helper to format values in human friendly form."""

    def __init__(self, settings: Settings, now: datetime | None = None) -> None:
        if settings.time_format not in TIME_FORMATS:
            allowed = ", ".join(TIME_FORMATS)
            raise ValueError(
                f"time_format must be one of {allowed}, not '{settings.time_format}'"
            )
        self.settings = settings
        self._now = now

    def now(self) -> datetime:
        return self._now if self._now is not None else datetime.now(timezone.utc)

    def absolute(self, moment: datetime) -> str:
        return moment.astimezone().strftime(self.settings.time_pattern)

    def relative(self, moment: datetime) -> str:
        """Past stamps go : ``3d 23h ago``, ``45s ago``, ``just now``, future
        ``in 3m``. The largest unit is shown, and the one below when it is not zero.
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
        """Formats stamp or returns ``-`` when there is none."""
        if moment is None:
            return "-"
        if self.settings.time_format == "relative":
            return self.relative(moment)
        if self.settings.time_format == "both":
            return f"{self.absolute(moment)} ({self.relative(moment)})"
        return self.absolute(moment)

    def day(self, moment: datetime) -> str:
        """The local calendar day for grouping."""
        return moment.astimezone().strftime(self.settings.day_pattern)

    def size(self, size: int) -> str:
        """Byte size in short form: ``12B``, ``3.4K``, ``1.2M``."""
        value = float(size)
        for unit in ("B", "K", "M", "G", "T"):
            if value < 1024 or unit == "T":
                if unit == "B":
                    return f"{int(value)}B"
                return f"{value:.1f}{unit}"
            value /= 1024
        return f"{int(value)}B"

    def path(self, path: str, width: int) -> str:
        """A path in ``width`` columns. One too long is cut in the middle, at slashes.

        The end of the path always stays, so two paths that differ in their
        last part alone stay apart: ``/home/u/dev/projects/app-one`` in 16
        columns is ``/home/…/app-one``. The start keeps at most the share of
        the room the settings give, and the end takes what the start leaves.
        A last part too long for the room on its own keeps its end.
        """
        width = max(width, 0)
        if len(path) <= width:
            return path
        mark = self.settings.path_ellipsis
        parts = path.split(SEP)
        # Room for the text on both sides of the mark, the slashes round it aside.
        room = width - len(mark) - 2 * len(SEP)
        if len(parts) == 1 or len(parts[-1]) > room + len(SEP):
            keep = width - len(mark)
            if keep <= 0:
                return path[-width:] if width else ""
            return mark + path[-keep:]
        # The end first, up to its share. Then the start, in what is left. Then
        # the end again, in case the start did not use all of its share.
        share = int(room * self.settings.path_head_share)
        cut = len(parts) - max(parts_that_fit(parts[::-1], room - share), 1)
        tail = SEP.join(parts[cut:])
        first = parts_that_fit(parts[: cut - 1], room - len(tail))
        head = SEP.join(parts[:first])
        left = room - len(head) if first else room + len(SEP)
        cut = len(parts) - max(parts_that_fit(parts[:first:-1], left), 1)
        tail = SEP.join(parts[cut:])
        if not first:
            return f"{mark}{SEP}{tail}"
        return f"{head}{SEP}{mark}{SEP}{tail}"

    def marks(self, session: Session) -> str:
        """The session state: live, fork, damaged."""
        parts = []
        if session.live:
            parts.append("[live]")
        if session.is_fork:
            parts.append("[fork]")
        if session.damaged:
            parts.append("[damaged]")
        return " ".join(parts)

    def titled(self, session: Session) -> str:
        """The title with its marks after it."""
        tag = self.marks(session)
        return f"{session.title} {tag}" if tag else session.title

    def describe(self, details: SessionDetails) -> list[tuple[str, str]]:
        """One session in full, as label and value pairs, in reading order."""
        session = details.session
        lines = [
            ("Id", session.id),
            ("Title", f"{session.title}  (from {session.title_source})"),
            ("Project", f"{session.project_path}  (from {session.project_source})"),
            ("Folder", session.project_key),
            ("Git branch", session.git_branch or "-"),
            ("Created", self.timestamp(session.created)),
            ("Last used", self.timestamp(session.last_used)),
            ("Claude Code", session.version or "-"),
            (
                "Transcript",
                f"{self.size(session.transcript_size)}  {session.transcript_path}",
            ),
        ]
        if session.sidecar_path is not None:
            agents = session.subagent_count
            noun = "subagent transcript" if agents == 1 else "subagent transcripts"
            lines.append(
                (
                    "Sidecar",
                    f"{self.size(session.sidecar_size)}  {session.sidecar_path}"
                    f"  ({agents} {noun})",
                )
            )
        else:
            lines.append(("Sidecar", "none"))
        lines.append(("Total", self.size(session.size)))
        if session.is_fork:
            lines.append(("Fork of", session.fork_parent or "-"))
            lines.append(
                (
                    "Inherited",
                    f"{self.size(details.inherited_bytes)} came from the parent",
                )
            )
        lines.append(("Live", f"yes  (pid {session.pid})" if session.live else "no"))
        lines.append(("Damaged", "yes" if session.damaged else "no"))
        return lines

    def trash_line(self, entries: list[TrashEntry]) -> str:
        """Info line about the trash content: ``Trash: 3 entries, 12.3M``."""
        if not entries:
            return "Trash: empty"
        noun = "entry" if len(entries) == 1 else "entries"
        total = sum(entry.size for entry in entries)
        return f"Trash: {len(entries)} {noun}, {self.size(total)}"

    def describe_entry(self, entry: TrashEntry) -> list[tuple[str, str]]:
        """One Trash entry"""
        lines = [
            ("Session", entry.session_id),
            ("Title", entry.title),
            ("Project", entry.project_path),
            ("Trashed", self.timestamp(entry.trashed_at)),
            ("Reason", entry.reason or "-"),
            ("Size", self.size(entry.size)),
            ("Entry", str(entry.path)),
        ]
        for part in entry.parts:
            label = part.kind.capitalize()
            lines.append((label, f"{self.size(part.size)}  {part.original}"))
        return lines
