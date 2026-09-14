"""The formatter: every time and size a human sees comes from here."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from conclaude.core.format import Formatter
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
