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
from datetime import datetime, timedelta, timezone

from conclaude.core.model import Figures, Session, SessionDetails, TrashEntry
from conclaude.core.settings import Settings

TIME_FORMATS = ("absolute", "relative", "both")
UNITS = (("y", 365 * 86400), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
# A path is cut at these.
SLASH = "/"


def parts_that_fit(parts: Sequence[str], sep: str, room: int) -> int:
    """How many of ``parts``, joined with ``sep`` from the first one, fit in ``room``."""
    count = used = 0
    for part in parts:
        need = len(part) + (len(sep) if count else 0)
        if used + need > room:
            break
        used += need
        count += 1
    return count


def plural(noun: str) -> str:
    """The English plural of a noun the tool uses: ``entry`` to ``entries``."""
    if noun.endswith("y"):
        return noun[:-1] + "ies"
    return noun + "s"


def plural_of(noun: str, count: int) -> str:
    """``noun`` in the number that fits ``count``: ``1 turn``, ``2 turns``, ``0 turns``."""
    return noun if count == 1 else plural(noun)


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

    def span(self, seconds: int) -> str:
        """A length of time in its two largest units: ``3d 23h``, ``45s``. Zero is ``0s``."""
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
            return text
        return "0s"

    def relative(self, moment: datetime) -> str:
        """Past stamps go : ``3d 23h ago``, ``45s ago``, ``just now``, future
        ``in 3m``. The largest unit is shown, and the one below when it is not zero.
        """
        seconds = int((self.now() - moment).total_seconds())
        if seconds == 0:
            return "just now"
        text = self.span(abs(seconds))
        return f"in {text}" if seconds < 0 else f"{text} ago"

    def duration(self, length: timedelta | None) -> str:
        """A length of time, or ``-`` when there is none."""
        if length is None:
            return "-"
        return self.span(int(length.total_seconds()))

    def count(self, value: int) -> str:
        """A whole number with a separator every three digits: ``1,234,567``."""
        return f"{value:,}"

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

        Two paths that differ in their last part alone stay apart:
        ``/home/u/dev/projects/app-one`` in 16 columns is ``/home/…/app-one``.
        """
        return self.cut(path, width, SLASH)

    def title(self, title: str, width: int) -> str:
        """A title in ``width`` columns. One too long is cut in the middle."""
        width = max(width, 0)
        if len(title) <= width:
            return title
        mark = self.settings.cut_mark
        room = width - len(mark)
        if room <= 0:
            return title[-width:] if width else ""
        head = int(room * self.settings.cut_head_share)
        tail = room - head
        return f"{title[:head]}{mark}{title[-tail:] if tail else ''}"

    def fit(self, text: str, width: int) -> str:
        """``text`` in ``width`` columns. One with a slash in it is cut like a path,
        at its slashes. Any other is cut like a title, by the character.
        """
        return self.path(text, width) if SLASH in text else self.title(text, width)

    def cut(self, text: str, width: int, sep: str) -> str:
        """``text`` in ``width`` cols. One too long is cut in the middle, at ``sep``."""
        width = max(width, 0)
        if len(text) <= width:
            return text
        mark = self.settings.cut_mark
        parts = text.split(sep)
        # Room for the text on both sides of the mark, the separators round it aside.
        room = width - len(mark) - 2 * len(sep)
        if len(parts) == 1 or len(parts[-1]) > room + len(sep):
            keep = width - len(mark)
            if keep <= 0:
                return text[-width:] if width else ""
            return mark + text[-keep:]

        share = int(room * self.settings.cut_head_share)
        drop = len(parts) - max(parts_that_fit(parts[::-1], sep, room - share), 1)
        tail = sep.join(parts[drop:])
        first = parts_that_fit(parts[: drop - 1], sep, room - len(tail))
        head = sep.join(parts[:first])
        left = room - len(head) if first else room + len(sep)
        drop = len(parts) - max(parts_that_fit(parts[:first:-1], sep, left), 1)
        tail = sep.join(parts[drop:])
        if not first:
            return f"{mark}{sep}{tail}"
        return f"{head}{sep}{mark}{sep}{tail}"

    @property
    def state_width(self) -> int:
        """The columns a state mark takes: one slot for every state."""
        return len(self.settings.state_marks)

    def marks(self, session: Session) -> str:
        """The session state, one slot each: live, fork, damaged."""
        states = (session.live, session.is_fork, session.damaged)
        return "".join(
            mark if on else self.settings.state_off
            for mark, on in zip(self.settings.state_marks, states)
        )

    def describe(self, details: SessionDetails) -> list[tuple[str, str]]:
        """One session in full, as label and value pairs, in reading order.

        The folder that holds the transcript and the sidecar is named once, in
        full. The two of them are then named by their name alone, so no line
        carries the whole path twice.
        """
        session = details.session
        lines = [
            ("Id", session.id),
            ("Title", f"{session.title}  (from {session.title_source})"),
            ("Project", f"{session.project_path}  (from {session.project_source})"),
            ("Folder", str(session.transcript_path.parent)),
            ("Git branch", session.git_branch or "-"),
            ("Created", self.timestamp(session.created)),
            ("Last used", self.timestamp(session.last_used)),
            ("Claude Code", session.version or "-"),
            (
                "Transcript",
                f"{self.size(session.transcript_size)}  {session.transcript_path.name}",
            ),
        ]
        if session.sidecar_path is not None:
            agents = session.subagent_count
            noun = "subagent transcript" if agents == 1 else "subagent transcripts"
            lines.append(
                (
                    "Sidecar",
                    f"{self.size(session.sidecar_size)}  {session.sidecar_path.name}"
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
        lines += self.describe_figures(details.figures)
        return lines

    def stale(self, text: str, figures: Figures) -> str:
        """``text`` with the stale mark in front when the figures are stale: ``*12``.

        In front, so a right-aligned column of numbers keeps its digits in line.
        """
        return f"{self.settings.stale_mark}{text}" if figures.stale else text

    def outdated(self, text: str, figures: Figures) -> str:
        """``text`` with the stale label in front when the figures are stale.

        For the details, where there is room for a word: ``(outdated) 12``.
        """
        return f"{self.settings.stale_label} {text}" if figures.stale else text

    def describe_figures(self, figures: Figures | None) -> list[tuple[str, str]]:
        """The deep-scan figures as label and value pairs, in reading order.

        With no figures there is one line, and it names the command to run.
        Stale figures carry the stale label on every value, and the last line
        says why.
        """
        if figures is None:
            return [("Deep scan", "none  (run 'conclaude scan')")]
        models = ", ".join(f"{name} ({count})" for name, count in figures.models)
        tools = ", ".join(f"{name} {count}" for name, count in figures.tools)
        tokens = (
            f"{self.count(figures.tokens)}  "
            f"({self.count(figures.input_tokens)} in, "
            f"{self.count(figures.output_tokens)} out)"
        )
        cached = (
            f"{self.count(figures.cache_read_tokens)} read, "
            f"{self.count(figures.cache_write_tokens)} written"
        )
        calls = self.count(figures.tool_calls)
        lines = [
            ("Turns", self.outdated(self.count(figures.turns), figures)),
            ("Tokens", self.outdated(tokens, figures)),
            ("Cache tokens", self.outdated(cached, figures)),
            ("Models", self.outdated(models or "-", figures)),
            ("Duration", self.outdated(self.duration(figures.duration), figures)),
            (
                "Tool calls",
                self.outdated(f"{calls}  ({tools})" if tools else calls, figures),
            ),
        ]
        scanned = self.timestamp(figures.scanned_at)
        if figures.stale:
            scanned += "  (the transcript changed since; run 'conclaude scan')"
        lines.append(("Scanned", scanned))
        return lines

    def figures_line(self, figures: Figures) -> str:
        """The figures of one session in one line, for a notification.

        The headline numbers alone: ``44 turns, 1,234 tokens, 12 tool calls``.
        Every one of them, and more, is on the details pane at the same time.
        """
        counted = (
            (figures.turns, "turn"),
            (figures.tokens, "token"),
            (figures.tool_calls, "tool call"),
        )
        return ", ".join(
            f"{self.count(value)} {plural_of(noun, value)}" for value, noun in counted
        )

    def scan_summary(self, read: int, kept: int, failed: int) -> str:
        """What a run of deep scans did: ``2 scanned, 1 already fresh, 0 failed``."""
        return f"{read} scanned, {kept} already fresh, {failed} failed"

    def counted(self, name: str, count: int) -> str:
        """A pane title with the count of what it shows: ``Projects (3)``, or ``(empty)``."""
        return f"{name} ({count})" if count else f"{name} (empty)"

    def summary(self, name: str, noun: str, sizes: Sequence[int]) -> str:
        """A pane title with a count and a total: ``Trash (3 entries, 12.3M total)``.

        ``noun`` names one of the things, ``session`` or ``entry``. Its plural
        follows English. One size per thing on view; none gives ``(empty)``.
        """
        if not sizes:
            return f"{name} (empty)"
        count = len(sizes)
        word = noun if count == 1 else plural(noun)
        return f"{name} ({count} {word}, {self.size(sum(sizes))} total)"

    def trash_key(self, entries: list[TrashEntry]) -> str:
        """The label of the key that opens the Trash: ``Trash (3)``, or ``Trash`` when empty."""
        return f"Trash ({len(entries)})" if entries else "Trash"

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
