"""The Trash as a collection: what is listed, what it adds up to, and that nothing ages out."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conclaude.core.errors import AmbiguousTrashEntry, TrashEntryNotFound
from conclaude.core.scan import folder_size
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from conclaude.core.trash import MANIFEST_NAME, trash_session
from tests.fabricate import FakeClaude, new_id, session_records, snapshot

PROJECT = "/home/u/dev/app"


def test_the_trash_lists_every_entry_newest_first(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """The trash lists every entry newest first."""
    ids = [new_id() for _ in range(3)]
    for index, sid in enumerate(ids):
        fake.transcript(
            PROJECT, sid, session_records(sid, PROJECT, custom_title=f"T{index}")
        )
    moments = [
        datetime(2026, 9, 14, 10, 0, second, tzinfo=timezone.utc)
        for second in (5, 3, 9)
    ]
    made = [
        trash_session(settings, store.find_session(sid), now=moment)
        for sid, moment in zip(ids, moments)
    ]

    entries = store.list_trash()

    assert [entry.id for entry in entries] == [made[2].id, made[0].id, made[1].id]
    assert [entry.session_id for entry in entries] == [ids[2], ids[0], ids[1]]
    assert [entry.trashed_at for entry in entries] == sorted(moments, reverse=True)
    assert [entry.title for entry in entries] == ["T2", "T0", "T1"]
    assert all(entry.size > 0 for entry in entries)


def test_an_entry_reads_back_exactly_as_it_was_written(
    fake: FakeClaude, store: SessionStore
) -> None:
    """An entry reads back exactly as it was written."""
    sid = new_id()
    fake.every_part(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    made = store.trash(sid, reason="pressed d")

    [read] = store.list_trash()

    assert read == made
    assert read.parts == made.parts
    assert read.trashed_at == made.trashed_at
    assert read.trashed_at.tzinfo is not None
    assert read.reason == "pressed d"
    assert read.size == made.size > 0


def test_total_size_is_the_sum_of_every_entry(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Total size is the sum of every entry."""
    assert store.trash_size() == 0
    first, second = new_id(), new_id()
    fake.every_part(PROJECT, first)
    fake.transcript(PROJECT, second)

    one = store.trash(first)
    two = store.trash(second)

    assert store.trash_size() == one.size + two.size
    assert one.size == sum(part.size for part in one.parts)
    manifest_bytes = (one.path / MANIFEST_NAME).stat().st_size
    assert one.size == folder_size(one.path) - manifest_bytes


def test_what_is_not_an_entry_is_not_listed(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """What is not an entry is not listed."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    entry = store.trash(sid)
    trash = settings.trash_dir
    good = json.loads((entry.path / MANIFEST_NAME).read_text(encoding="utf-8"))
    (trash / "stray.txt").write_bytes(b"x")
    (trash / "no-manifest" / "claude").mkdir(parents=True)
    (trash / "bad-json").mkdir()
    (trash / "bad-json" / MANIFEST_NAME).write_bytes(b"{")
    (trash / "wrong-version").mkdir()
    (trash / "wrong-version" / MANIFEST_NAME).write_text(
        json.dumps({**good, "version": 99}), encoding="utf-8"
    )
    (trash / "missing-fields").mkdir()
    (trash / "missing-fields" / MANIFEST_NAME).write_text(
        '{"version": 1}', encoding="utf-8"
    )
    (trash / "bad-part").mkdir()
    (trash / "bad-part" / MANIFEST_NAME).write_text(
        json.dumps({**good, "parts": [{"kind": "transcript"}]}), encoding="utf-8"
    )
    (trash / "linked").symlink_to(entry.path)
    before = snapshot(trash)

    entries = store.list_trash()

    assert [found.id for found in entries] == [entry.id]
    assert store.trash_size() == entry.size
    assert snapshot(trash) == before


def test_the_trash_never_empties_itself(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """The trash never empties itself."""
    old, first, second = new_id(), new_id(), new_id()
    for sid in (old, first, second):
        fake.transcript(PROJECT, sid)
    long_ago = datetime(2019, 1, 1, tzinfo=timezone.utc)
    ancient = trash_session(settings, store.find_session(old), now=long_ago)
    one = store.trash(first)
    two = store.trash(second)
    before = snapshot(ancient.path)

    for _ in range(3):
        store.list_trash()
        store.trash_size()
    store.restore(one.id)
    store.purge(two.id)

    [kept] = store.list_trash()
    assert kept.id == ancient.id
    assert kept.trashed_at == long_ago
    assert snapshot(ancient.path) == before


def test_an_entry_is_found_by_its_id_or_by_a_unique_prefix(
    fake: FakeClaude, store: SessionStore
) -> None:
    """An entry is found by its id or by a unique prefix."""
    first = "aaaaaaaa-0000-4000-8000-000000000001"
    second = "aaaabbbb-0000-4000-8000-000000000002"
    fake.transcript(PROJECT, first)
    fake.transcript(PROJECT, second)
    one = store.trash(first)
    two = store.trash(second)
    stamp = len(one.id) - len(first)

    assert store.find_entry(one.id) == one
    assert store.find_entry(first) == one
    assert store.find_entry("aaaaa") == one
    assert store.find_entry("aaaab") == two
    assert store.find_entry(one.id[: stamp + 5]) == one
    with pytest.raises(AmbiguousTrashEntry, match="'aaaa' matches 2 Trash entries"):
        store.find_entry("aaaa")
    with pytest.raises(TrashEntryNotFound, match="no Trash entry matches 'nope'"):
        store.find_entry("nope")
