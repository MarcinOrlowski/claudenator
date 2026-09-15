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
from typing import Any

import pytest

from conclaude.core.format import Formatter
from conclaude.core.model import Figures, Part, Session, SessionDetails, TrashEntry
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
    settings = Settings(time_format="absolute", time_pattern="%Y-%m-%dT%H:%M:%S")

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


def test_a_duration_shows_its_two_largest_units_and_a_missing_one_is_a_dash() -> None:
    """A duration shows its two largest units, like a relative time with no 'ago'."""
    fmt = Formatter(Settings())

    assert fmt.duration(None) == "-"
    assert fmt.duration(timedelta(0)) == "0s"
    assert fmt.duration(timedelta(seconds=59)) == "59s"
    assert fmt.duration(timedelta(hours=2, minutes=11, seconds=16)) == "2h 11m"
    assert fmt.duration(timedelta(days=3)) == "3d"


def test_a_count_carries_a_separator_every_three_digits() -> None:
    """A count carries a separator every three digits."""
    fmt = Formatter(Settings())

    assert fmt.count(0) == "0"
    assert fmt.count(999) == "999"
    assert fmt.count(1000) == "1,000"
    assert fmt.count(83321309) == "83,321,309"


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


def test_a_path_that_fits_is_left_alone() -> None:
    """A path that fits is left alone."""
    fmt = Formatter(Settings())

    assert fmt.path("/home/u/dev/app", 15) == "/home/u/dev/app"
    assert fmt.path("/home/u/dev/app", 40) == "/home/u/dev/app"


def test_a_long_path_is_cut_in_the_middle_at_the_slashes_and_its_end_stays() -> None:
    """A long path is cut in the middle, at the slashes. Its end always stays whole.

    So two paths that differ in their last part alone stay apart.
    """
    fmt = Formatter(Settings())

    assert fmt.path("foo/bar/long/long2/other/long", 12) == "foo/…/long"
    assert fmt.path("/home/carlos/dev/projects/claude-sessions", 30) == (
        "/home/carlos/…/claude-sessions"
    )
    assert fmt.path("/home/u/dev/projects/app-one", 16) == "/home/…/app-one"
    assert fmt.path("/home/u/dev/projects/app-two", 16) == "/home/…/app-two"


def test_the_end_takes_the_room_the_start_leaves() -> None:
    """The end takes the room the start leaves unused."""
    fmt = Formatter(Settings())

    assert fmt.path("verylonghead/aaaa/bbbb/cccc/end", 20) == "…/aaaa/bbbb/cccc/end"


def test_a_last_part_too_long_on_its_own_keeps_its_end() -> None:
    """A last part too long for the room on its own keeps its end. So does a bare name."""
    fmt = Formatter(Settings())

    assert fmt.path("/a/b/averyverylongsegment", 10) == "…ngsegment"
    assert fmt.path("averyverylongname", 8) == "…ongname"
    assert fmt.path("/x/y", 1) == "y"
    assert fmt.path("/x/y", 0) == ""


def test_the_mark_and_the_share_of_the_start_come_from_the_settings() -> None:
    """The mark and the share of the start come from the settings."""
    path = "foo/bar/long/long2/other/long"

    assert Formatter(Settings(cut_mark="...")).path(path, 12) == "foo/.../long"
    assert (
        Formatter(Settings(cut_head_share=0.0)).path(path, 20) == "…/long2/other/long"
    )
    assert (
        Formatter(Settings(cut_head_share=0.5)).path(path, 20) == "foo/bar/long/…/long"
    )


def test_a_long_title_is_cut_in_the_middle_by_the_character_and_its_end_stays() -> None:
    """A long title is cut in the middle, by the character, and its end stays.

    A title is not cut at its spaces: one long word would take the rest with it.
    """
    fmt = Formatter(Settings())
    title = "konfigurator-vs-api-round-2 [live]"

    assert fmt.title(title, 20) == "konf…-round-2 [live]"
    assert fmt.title(title, 12) == "ko…-2 [live]"
    assert fmt.title(title, 1) == "]"
    assert fmt.title(title, 0) == ""
    assert fmt.title("Short", 30) == "Short"
    assert Formatter(Settings(cut_head_share=0.0)).title(title, 20) == (
        "…-api-round-2 [live]"
    )
    assert Formatter(Settings(cut_head_share=1.0)).title(title, 20) == (
        "konfigurator-vs-api…"
    )


@pytest.mark.parametrize("width", range(0, 60, 3))
def test_a_cut_path_never_goes_past_its_room(width: int) -> None:
    """A cut path never goes past its room, and it ends as the path ends."""
    path = "/home/u/dev/projects/some-long-folder-name/app-one"
    cut = Formatter(Settings()).path(path, width)

    if width >= len(path):
        assert cut == path
    else:
        assert len(cut) <= width
        assert path.endswith(cut[-1:])


def test_fit_cuts_a_path_at_its_slashes_and_any_other_text_by_the_character() -> None:
    """Fit cuts a text with a slash in it like a path, and any other like a title."""
    fmt = Formatter(Settings())

    assert fmt.fit("1.9M  /home/u/.claude/projects/-p/s.jsonl", 24) == (
        "1.9M  /home/…/-p/s.jsonl"
    )
    assert fmt.fit("konfigurator-vs-api-round-2 [live]", 20) == "konf…-round-2 [live]"
    assert fmt.fit("short", 20) == "short"


def session(**overrides: Any) -> Session:
    """A session in ``/c/projects/-home-u-p``, with a sidecar of three subagents."""
    fields: dict[str, Any] = dict(
        id="s",
        project_key="-home-u-p",
        project_path="/home/u/p",
        project_source="transcript",
        title="Hello",
        title_source="custom",
        transcript_path=Path("/c/projects/-home-u-p/s.jsonl"),
        transcript_size=100,
        last_used=NOW,
        created=NOW,
        sidecar_path=Path("/c/projects/-home-u-p/s"),
        sidecar_size=2048,
        subagent_count=3,
        git_branch="dev",
        version="2.1.270",
        fork_parent=None,
        damaged=False,
    )
    fields.update(overrides)
    return Session(**fields)


def test_the_state_marks_hold_one_slot_for_every_state() -> None:
    """The state marks hold one slot per state: live, fork, damaged."""
    fmt = Formatter(Settings())

    assert fmt.marks(session()) == "---"
    assert fmt.marks(session(live=True)) == "L--"
    assert fmt.marks(session(fork_parent="mum")) == "-F-"
    assert fmt.marks(session(damaged=True)) == "--D"
    assert fmt.marks(session(live=True, fork_parent="mum")) == "LF-"
    assert fmt.marks(session(live=True, fork_parent="mum", damaged=True)) == "LFD"
    assert fmt.state_width == 3
    own = Formatter(Settings(state_marks="lfd", state_off="."))
    assert own.marks(session(live=True, damaged=True)) == "l.d"
    assert own.state_width == 3


def test_describe_names_the_folder_once_and_the_files_in_it_by_their_name() -> None:
    """Describe names the folder once, in full. The transcript and the sidecar go by name.

    So no line carries the whole path twice, and none is longer than it must be.
    """
    fmt = Formatter(Settings(), now=NOW)
    lines = dict(fmt.describe(SessionDetails(session(), 0)))
    alone = session(sidecar_path=None, sidecar_size=0, subagent_count=0)
    without = dict(fmt.describe(SessionDetails(alone, 0)))

    assert lines["Folder"] == "/c/projects/-home-u-p"
    assert lines["Transcript"] == "100B  s.jsonl"
    assert lines["Sidecar"] == "2.0K  s  (3 subagent transcripts)"
    assert lines["Total"] == "2.1K"
    assert without["Sidecar"] == "none"
    assert without["Total"] == "100B"


def figures(**overrides: Any) -> Figures:
    """The figures of a deep scan done an hour before ``NOW``, of a two-hour session."""
    fields: dict[str, Any] = dict(
        transcript_path=Path("/c/projects/-home-u-p/s.jsonl"),
        transcript_size=100,
        transcript_mtime_ns=1_000,
        scanned_at=ago(hours=1),
        turns=12,
        input_tokens=1_234,
        output_tokens=56_789,
        cache_read_tokens=2_000_000,
        cache_write_tokens=30_000,
        models=(("claude-opus-5", 30), ("claude-fable-5-1", 4)),
        tools=(("Bash", 20), ("Edit", 5)),
        first_at=ago(hours=3),
        last_at=ago(hours=1),
    )
    fields.update(overrides)
    return Figures(**fields)


def test_describe_ends_with_the_deep_scan_figures_or_the_command_that_makes_them() -> (
    None
):
    """The figures come last. Without any, one line names the command to run."""
    fmt = Formatter(Settings(), now=NOW)

    with_figures = fmt.describe(SessionDetails(session(), 0, figures()))
    without = fmt.describe(SessionDetails(session(), 0))

    assert [label for label, _ in with_figures][-7:] == [
        "Damaged",
        "Turns",
        "Tokens",
        "Cache tokens",
        "Models",
        "Duration",
        "Tool calls",
        "Scanned",
    ][1:]
    assert [label for label, _ in without][-2:] == ["Damaged", "Deep scan"]
    assert dict(without)["Deep scan"] == "none  (run 'conclaude scan')"


def test_describe_figures_names_every_number_in_full() -> None:
    """Every number is exact, with separators. Models and tools carry their counts."""
    fmt = Formatter(Settings(), now=NOW)

    lines = fmt.describe_figures(figures())

    assert lines == [
        ("Turns", "12"),
        ("Tokens", "2,088,023  (1,234 in, 56,789 out)"),
        ("Cache tokens", "2,000,000 read, 30,000 written"),
        ("Models", "claude-opus-5 (30), claude-fable-5-1 (4)"),
        ("Duration", "2h"),
        ("Tool calls", "25  (Bash 20, Edit 5)"),
        ("Scanned", "1h ago"),
    ]


def test_describe_figures_with_nothing_counted_shows_dashes_not_blanks() -> None:
    """A scan that found no answer at all still reports, with a dash for the models."""
    fmt = Formatter(Settings(), now=NOW)

    lines = dict(
        fmt.describe_figures(
            figures(models=(), tools=(), first_at=None, last_at=None, turns=0)
        )
    )

    assert lines["Turns"] == "0"
    assert lines["Models"] == "-"
    assert lines["Duration"] == "-"
    assert lines["Tool calls"] == "0"


def test_figures_line_says_the_headline_numbers_in_one_line() -> None:
    """The line a notification carries: the three numbers, each with its noun."""
    fmt = Formatter(Settings(), now=NOW)

    many = fmt.figures_line(figures())
    one = fmt.figures_line(
        figures(
            turns=1,
            input_tokens=1,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            tools=(("Bash", 1),),
        )
    )

    assert many == "12 turns, 2,088,023 tokens, 25 tool calls"
    assert one == "1 turn, 1 token, 1 tool call"


def test_scan_summary_counts_what_a_run_of_scans_did() -> None:
    """One wording for the screen and for the command line."""
    fmt = Formatter(Settings(), now=NOW)

    assert fmt.scan_summary(2, 1, 0) == "2 scanned, 1 already fresh, 0 failed"
    assert fmt.scan_summary(0, 0, 3) == "0 scanned, 0 already fresh, 3 failed"


def test_stale_figures_carry_the_label_on_every_value_and_say_why() -> None:
    """Old numbers stay on view. In the details each carries the stale label in
    front, a word, and the last line says the transcript changed since. The
    short mark is for a table cell. Both come from the settings.
    """
    fmt = Formatter(Settings(), now=NOW)
    own = Formatter(Settings(stale_mark="?", stale_label="OLD"), now=NOW)

    lines = dict(fmt.describe_figures(figures(stale=True)))
    marked = dict(own.describe_figures(figures(stale=True)))

    assert lines["Turns"] == "(outdated) 12"
    assert lines["Tokens"] == "(outdated) 2,088,023  (1,234 in, 56,789 out)"
    assert lines["Cache tokens"] == "(outdated) 2,000,000 read, 30,000 written"
    assert lines["Models"] == "(outdated) claude-opus-5 (30), claude-fable-5-1 (4)"
    assert lines["Duration"] == "(outdated) 2h"
    assert lines["Tool calls"] == "(outdated) 25  (Bash 20, Edit 5)"
    assert lines["Scanned"] == (
        "1h ago  (the transcript changed since; run 'conclaude scan')"
    )
    assert marked["Turns"] == "OLD 12"
    assert fmt.stale("12", figures(stale=True)) == "*12"
    assert own.stale("12", figures(stale=True)) == "?12"
    assert fmt.stale("12", figures()) == "12"
    assert fmt.outdated("12", figures()) == "12"


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


def test_a_counted_title_carries_the_count_or_says_empty() -> None:
    """A counted title carries the count. Zero says empty instead."""
    counted = Formatter(Settings()).counted

    assert counted("Projects", 0) == "Projects (empty)"
    assert counted("Projects", 1) == "Projects (1)"
    assert counted("Days", 12) == "Days (12)"


def test_a_summary_title_counts_the_things_and_sums_their_size() -> None:
    """A summary title counts the things, in the right plural, and sums their size."""
    summary = Formatter(Settings()).summary

    assert summary("Trash", "entry", []) == "Trash (empty)"
    assert summary("Trash", "entry", [1000]) == "Trash (1 entry, 1000B total)"
    assert summary("Trash", "entry", [1000, 2048]) == "Trash (2 entries, 3.0K total)"
    assert (
        summary("Sessions", "session", [1, 2, 3]) == "Sessions (3 sessions, 6B total)"
    )


def test_trash_key_carries_the_count_and_nothing_when_the_trash_is_empty() -> None:
    """The Trash key carries the count. An empty Trash puts nothing after the word."""
    key = Formatter(Settings()).trash_key

    assert key([]) == "Trash"
    assert key([entry(1000)]) == "Trash (1)"
    assert key([entry(1000), entry(2048)]) == "Trash (2)"


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
