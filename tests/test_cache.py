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

import os
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from conclaude.core.cache import Cache
from conclaude.core.errors import CacheDamaged
from conclaude.core.settings import Settings
from conclaude.core.stats import deep_scan
from tests.fabricate import FakeClaude, answer_records, dump_line, new_id, prompt_record

PROJECT = "/p/x"
NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_the_cache_starts_empty_and_gives_back_what_was_put(
    fake: FakeClaude, settings: Settings
) -> None:
    """Nothing before a put. After it, the same figures come back, fresh, from a new
    cache object too, because they live in a file in the tool's own folder.
    """
    sid = new_id()
    path = fake.transcript(PROJECT, sid, answer_records(sid, tools=["Bash"]))
    cache = Cache(settings)
    figures = deep_scan(path, now=NOW)

    before = cache.get(path)
    cache.put(figures)
    after = cache.get(path)
    again = Cache(settings).get(path)

    assert before is None
    assert after == figures
    assert again == figures
    assert after.stale is False
    assert settings.cache_file.is_file()
    assert settings.cache_file.parent == settings.data_dir


def test_a_changed_transcript_keeps_its_old_figures_marked_stale(
    fake: FakeClaude, settings: Settings
) -> None:
    """After the transcript grows, the old numbers still come back, marked stale.
    A new scan put in their place is fresh again. A change of time alone is enough.
    """
    sid = new_id()
    path = fake.transcript(PROJECT, sid, answer_records(sid))
    cache = Cache(settings)
    first = deep_scan(path, now=NOW)
    cache.put(first)

    with open(path, "ab") as handle:
        handle.write(dump_line(prompt_record(sid, "More")))
    grown = cache.get(path)
    cache.put(deep_scan(path, now=NOW))
    rescanned = cache.get(path)
    os.utime(path, (1_700_000_000, 1_700_000_000))
    touched = cache.get(path)

    assert grown is not None and grown.stale is True
    assert grown.turns == 0
    assert replace(grown, stale=False) == first
    assert rescanned.turns == 1
    assert rescanned.stale is False
    assert touched is not None and touched.stale is True


def test_a_gone_transcript_reads_stale_until_the_cache_forgets_it(
    fake: FakeClaude, settings: Settings
) -> None:
    """Figures of a removed transcript are stale. ``forget_missing`` drops them and
    nothing else, and says how many went.
    """
    gone, kept = new_id(), new_id()
    gone_path = fake.transcript(PROJECT, gone, answer_records(gone))
    kept_path = fake.transcript(PROJECT, kept, answer_records(kept))
    cache = Cache(settings)
    cache.put(deep_scan(gone_path, now=NOW))
    cache.put(deep_scan(kept_path, now=NOW))

    gone_path.unlink()
    orphan = cache.get(gone_path)
    dropped = cache.forget_missing()

    assert orphan is not None and orphan.stale is True
    assert dropped == 1
    assert cache.get(gone_path) is None
    assert cache.get(kept_path) is not None
    assert cache.forget_missing() == 0


def test_a_missing_cache_file_is_an_empty_cache(settings: Settings) -> None:
    """With no cache file yet, a get and a forget both answer without making one."""
    cache = Cache(settings)

    assert cache.get(settings.projects_dir / "x.jsonl") is None
    assert cache.forget_missing() == 0
    assert not settings.cache_file.exists()


def test_a_damaged_cache_reads_as_empty_and_refuses_a_put(
    fake: FakeClaude, settings: Settings
) -> None:
    """A cache file that is not a database gives no figures, so a list still works.
    A put names the file and asks for its removal.
    """
    sid = new_id()
    path = fake.transcript(PROJECT, sid, answer_records(sid))
    settings.cache_file.parent.mkdir(parents=True)
    settings.cache_file.write_bytes(b"this is not sqlite at all, not even close\n")
    cache = Cache(settings)

    assert cache.get(path) is None
    with pytest.raises(CacheDamaged, match="remove it and scan again") as caught:
        cache.put(deep_scan(path, now=NOW))
    assert caught.value.path == settings.cache_file
