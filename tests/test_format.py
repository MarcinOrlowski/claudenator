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

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conclaude.core.format import Formatter
from conclaude.core.model import Part, TrashEntry
from conclaude.core.settings import Settings

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


def ago(**delta: int) -> datetime:
    """A moment some time before ``NOW``."""
    return NOW - timedelta(**delta)


def test_absolute_shows_local_time_to_the_second() -> None:
    """Absolute shows local time to the second."""
    settings = Settings(time_format="absolute")
    text = Formatter(settings, now=NOW).timestamp(ago(seconds=5))

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text)
    assert text == ago(seconds=5).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def test_absolute_pattern_comes_from_the_settings() -> None:
    """Absolute pattern comes from the settings."""
    settings = Settings(time_pattern="%Y-%m-%dT%H:%M:%S")

    assert "T" in Formatter(settings, now=NOW).timestamp(NOW)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (NOW, "just now"),
        (ago(seconds=45), "45s ago"),
        (ago(minutes=2, seconds=5), "2m 5s ago"),
        (ago(hours=2, minutes=5), "2h 5m ago"),
        (ago(hours=2), "2h ago"),
        (ago(days=3, hours=23), "3d 23h ago"),
        (ago(days=3, minutes=5), "3d ago"),
        (ago(days=377), "1y 12d ago"),
        (NOW + timedelta(minutes=3), "in 3m"),
    ],
)
def test_relative_shows_the_two_largest_units(moment: datetime, expected: str) -> None:
    """Relative shows the two largest units."""
    settings = Settings(time_format="relative")

    assert Formatter(settings, now=NOW).timestamp(moment) == expected


def test_both_shows_absolute_then_relative() -> None:
    """Both shows absolute then relative."""
    settings = Settings(time_format="both")
    formatter = Formatter(settings, now=NOW)
    moment = ago(days=3, hours=23)

    assert formatter.timestamp(moment) == f"{formatter.absolute(moment)} (3d 23h ago)"


def test_a_missing_moment_is_a_dash() -> None:
    """A missing moment is a dash."""
    assert Formatter(Settings()).timestamp(None) == "-"


def test_an_unknown_time_format_is_refused() -> None:
    """An unknown time format is refused."""
    with pytest.raises(ValueError, match="time_format must be one of"):
        Formatter(Settings(time_format="fancy"))


def test_now_is_live_unless_fixed() -> None:
    """Now is live unless fixed."""
    formatter = Formatter(Settings(time_format="relative"))

    assert formatter.timestamp(datetime.now(timezone.utc)) == "just now"


def test_size() -> None:
    """Size."""
    size = Formatter(Settings()).size

    assert size(0) == "0B"
    assert size(1023) == "1023B"
    assert size(1024) == "1.0K"
    assert size(3 * 1024 * 1024 + 200 * 1024) == "3.2M"
    assert size(5 * 1024**4) == "5.0T"


def test_day_is_the_local_calendar_day_in_the_pattern_the_settings_give() -> None:
    """Day is the local calendar day, in the pattern the settings give. Never a time."""
    day = Formatter(Settings(), now=NOW).day(NOW)

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
    assert day == NOW.astimezone().strftime("%Y-%m-%d")
    assert Formatter(Settings(day_pattern="%d.%m.%Y")).day(
        NOW
    ) == NOW.astimezone().strftime("%d.%m.%Y")


def entry(size: int, parts: tuple[Part, ...] = ()) -> TrashEntry:
    """A Trash entry of a given size, made of the parts given or one part of that size."""
    if not parts:
        parts = (
            Part(
                kind="transcript",
                original=Path("/c/projects/p/s.jsonl"),
                stored=Path("claude/projects/p/s.jsonl"),
                is_dir=False,
                size=size,
            ),
        )
    return TrashEntry(
        id="2026-09-14T12-00-00_s",
        path=Path("/t/2026-09-14T12-00-00_s"),
        session_id="s",
        trashed_at=NOW,
        reason=None,
        title="Hello",
        project_path="/home/u/p",
        parts=parts,
    )


def test_trash_line_counts_the_entries_and_sums_their_size() -> None:
    """The Trash line counts the entries and sums their size."""
    line = Formatter(Settings()).trash_line

    assert line([]) == "Trash: empty"
    assert line([entry(1000)]) == "Trash: 1 entry, 1000B"
    assert line([entry(1000), entry(2048)]) == "Trash: 2 entries, 3.0K"


def test_describe_entry_names_the_session_the_moment_the_size_and_every_part() -> None:
    """Describe entry names the session, the moment, the size and every part with its place."""
    fmt = Formatter(Settings(time_format="absolute"), now=NOW)
    parts = (
        Part("transcript", Path("/c/projects/p/s.jsonl"), Path("claude/x"), False, 100),
        Part("sidecar", Path("/c/projects/p/s"), Path("claude/y"), True, 2048),
        Part("session-env", Path("/c/session-env/s"), Path("claude/z"), True, 4),
    )
    described = fmt.describe_entry(entry(0, parts))

    assert described == [
        ("Session", "s"),
        ("Title", "Hello"),
        ("Project", "/home/u/p"),
        ("Trashed", fmt.timestamp(NOW)),
        ("Reason", "-"),
        ("Size", "2.1K"),
        ("Entry", "/t/2026-09-14T12-00-00_s"),
        ("Transcript", "100B  /c/projects/p/s.jsonl"),
        ("Sidecar", "2.0K  /c/projects/p/s"),
        ("Session-env", "4B  /c/session-env/s"),
    ]
    with_reason = fmt.describe_entry(replace(entry(0, parts), reason="pressed d"))
    assert with_reason[4] == ("Reason", "pressed d")
