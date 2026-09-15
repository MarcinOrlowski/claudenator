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

from datetime import datetime, timedelta, timezone

import pytest

from conclaude.core.stats import deep_scan
from tests.fabricate import (
    FakeClaude,
    answer_records,
    new_id,
    prompt_record,
    session_records,
)

PROJECT = "/p/x"
NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_deep_scan_counts_turns_tokens_models_tools_and_the_duration(
    fake: FakeClaude,
) -> None:
    """Deep scan counts the prompts typed, every token once per answer, the models,
    the tool calls by name, and the time from the first record to the last.
    """
    sid = new_id()
    records = session_records(sid, PROJECT, human=None)
    records += [prompt_record(sid, "Fix it", "2026-09-14T08:00:00.000Z")]
    records += answer_records(
        sid, tools=["Bash", "Read", "Bash"], timestamp="2026-09-14T08:00:05.000Z"
    )
    records += [prompt_record(sid, "Thanks", "2026-09-14T09:30:00.000Z")]
    records += answer_records(
        sid,
        model="claude-fable-5-1",
        usage={"input_tokens": 1, "output_tokens": 2},
        timestamp="2026-09-14T09:30:07.000Z",
    )
    path = fake.transcript(PROJECT, sid, records)

    figures = deep_scan(path, now=NOW)

    assert figures.transcript_path == path
    assert figures.transcript_size == path.stat().st_size
    assert figures.transcript_mtime_ns == path.stat().st_mtime_ns
    assert figures.scanned_at == NOW
    assert figures.stale is False
    assert figures.turns == 2
    # The first answer is four records with one usage. It counts once.
    assert (figures.input_tokens, figures.output_tokens) == (11, 22)
    assert (figures.cache_read_tokens, figures.cache_write_tokens) == (300, 40)
    assert figures.tokens == 373
    assert figures.models == (("claude-fable-5-1", 1), ("claude-opus-5", 1))
    assert figures.tools == (("Bash", 2), ("Read", 1))
    assert figures.tool_calls == 3
    assert figures.first_at == datetime(2026, 9, 14, 7, 18, 50, 439000, timezone.utc)
    assert figures.last_at == datetime(2026, 9, 14, 9, 30, 7, tzinfo=timezone.utc)
    assert figures.duration == timedelta(
        hours=2, minutes=11, seconds=16, microseconds=561000
    )


def test_deep_scan_leaves_out_what_claude_code_made_itself(fake: FakeClaude) -> None:
    """A message with no API call behind it counts for nothing: not as a turn, not as
    tokens, not as a model. Injected user records are not turns either.
    """
    sid = new_id()
    records = session_records(sid, PROJECT, human=None)
    records += answer_records(sid, api_error=True, tools=["Bash"])
    records += [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "x"}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>"}},
    ]
    path = fake.transcript(PROJECT, sid, records)

    figures = deep_scan(path, now=NOW)

    assert figures.turns == 0
    assert figures.tokens == 0
    assert figures.models == ()
    assert figures.tools == ()


def test_deep_scan_skips_a_line_that_will_not_parse(fake: FakeClaude) -> None:
    """A bad line is skipped and the rest still counts. A file of bad lines counts zero."""
    sid, broken = new_id(), new_id()
    records: list = [b"\xff\xfe not json\n", *answer_records(sid), b"{oops\n"]
    path = fake.transcript(PROJECT, sid, records)
    garbage = fake.transcript(PROJECT, broken, raw=b"\xff\xfe\n\xff\n")

    figures = deep_scan(path, now=NOW)
    nothing = deep_scan(garbage, now=NOW)

    assert figures.models == (("claude-opus-5", 1),)
    assert figures.tokens == 370
    assert nothing.turns == nothing.tokens == 0
    assert nothing.first_at is None
    assert nothing.duration is None


def test_deep_scan_of_a_missing_file_raises(fake: FakeClaude) -> None:
    """A file that cannot be read raises the operating system's error."""
    with pytest.raises(OSError):
        deep_scan(fake.project(PROJECT) / f"{new_id()}.jsonl")


def test_figures_to_dict_holds_every_number_and_the_times_to_the_second(
    fake: FakeClaude,
) -> None:
    """The JSON form carries the totals, the models and tools as maps, and ISO times."""
    sid = new_id()
    records = [prompt_record(sid, "Go", "2026-09-14T08:00:00.500Z")]
    records += answer_records(sid, tools=["Edit"], timestamp="2026-09-14T08:01:00.000Z")
    path = fake.transcript(PROJECT, sid, records)

    data = deep_scan(path, now=NOW).to_dict()

    assert data == {
        "scanned_at": "2026-09-15T12:00:00+00:00",
        "stale": False,
        "turns": 1,
        "tokens": 370,
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_tokens": 300,
        "cache_write_tokens": 40,
        "models": {"claude-opus-5": 1},
        "tool_calls": 1,
        "tools": {"Edit": 1},
        "first_at": "2026-09-14T08:00:00+00:00",
        "last_at": "2026-09-14T08:01:00+00:00",
        "duration_seconds": 59,
    }
