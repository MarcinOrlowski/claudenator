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

import fcntl
import os
import shutil
import threading

import pytest

from conclaude.core.errors import PurgeFailed, TrashEntryNotFound
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from conclaude.core.trash import MANIFEST_NAME, purge_entry
from tests.fabricate import FakeClaude, new_id, snapshot

PROJECT = "/home/u/dev/app"


def test_purging_removes_the_entry_and_nothing_else(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """Purging removes the entry and nothing else."""
    gone, kept, alive = new_id(), new_id(), new_id()
    for sid in (gone, kept, alive):
        fake.every_part(PROJECT, sid)
    fake.shared()
    fake.history(alive, PROJECT)
    (settings.claude_dir.parent / "keep.txt").write_bytes(b"mine\n")
    entry_gone = store.trash(gone)
    entry_kept = store.trash(kept)
    root = settings.claude_dir.parent
    before = snapshot(root)
    prefix = entry_gone.path.relative_to(root).as_posix()
    removed = {key for key in before if key == prefix or key.startswith(prefix + "/")}
    assert len(removed) > 1

    purged = store.purge(entry_gone.id)

    assert purged == entry_gone
    assert not entry_gone.path.exists()
    after = snapshot(root)
    assert after == {key: value for key, value in before.items() if key not in removed}
    assert [found.id for found in store.list_trash()] == [entry_kept.id]
    assert store.trash_size() == entry_kept.size
    assert [session.id for session in store.list_sessions()] == [alive]


def test_purge_of_removes_an_entry_in_hand_and_lists_nothing(
    fake: FakeClaude, store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``purge_of`` removes an entry already in hand. The Trash is not listed again."""
    sid = new_id()
    fake.every_part(PROJECT, sid)
    entry = store.trash(sid)
    monkeypatch.setattr(
        store, "list_trash", lambda: pytest.fail("the Trash was listed again")
    )

    purged = store.purge_of(entry)

    assert purged == entry
    assert not entry.path.exists()
    assert SessionStore(store.settings).list_trash() == []


def test_a_purged_link_does_not_touch_its_target(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A purged link does not touch its target."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    target = settings.claude_dir.parent / "elsewhere"
    target.mkdir()
    (target / "env").write_bytes(b"A=1\n")
    (fake.root / "session-env" / sid).symlink_to(target)
    entry = store.trash(sid)
    assert (entry.path / "claude" / "session-env" / sid).is_symlink()

    store.purge(entry.id)

    assert not entry.path.exists()
    assert (target / "env").read_bytes() == b"A=1\n"


def test_purge_finds_an_entry_by_a_prefix_of_the_session_id(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Purge finds an entry by a prefix of the session id."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    entry = store.trash(sid)

    purged = store.purge(sid[:8])

    assert purged.id == entry.id
    assert store.list_trash() == []


def test_purging_an_unknown_entry_fails(store: SessionStore) -> None:
    """Purging an unknown entry fails."""
    with pytest.raises(TrashEntryNotFound, match="no Trash entry matches 'nope'"):
        store.purge("nope")


def test_an_entry_gone_between_the_list_and_the_purge_fails_cleanly(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """An entry gone between the list and the purge fails cleanly."""
    sid, other = new_id(), new_id()
    fake.transcript(PROJECT, sid)
    fake.transcript(PROJECT, other)
    entry = store.trash(sid)
    kept = store.trash(other)
    SessionStore(settings).purge(entry.id)

    with pytest.raises(TrashEntryNotFound, match=entry.id):
        purge_entry(settings, entry)

    assert [found.id for found in store.list_trash()] == [kept.id]


def test_the_lock_is_held_for_the_whole_purge(
    fake: FakeClaude, settings: Settings
) -> None:
    """The lock is held for the whole purge."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    store = SessionStore(settings)
    entry = store.trash(sid)
    result: list = []

    def run() -> None:
        result.append(store.purge(entry.id))

    with open(settings.trash_lock_file, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(target=run)
        worker.start()
        worker.join(timeout=0.3)
        assert worker.is_alive()
        assert entry.path.is_dir()
        assert result == []
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert not entry.path.exists()
    [purged] = result
    assert purged.id == entry.id


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_entry_that_cannot_be_removed_names_the_path(
    fake: FakeClaude, store: SessionStore
) -> None:
    """An entry that cannot be removed names the path."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    entry = store.trash(sid)
    entry.path.chmod(0o500)
    try:
        with pytest.raises(PurgeFailed, match="could not remove ") as caught:
            store.purge(entry.id)
    finally:
        entry.path.chmod(0o700)
        shutil.rmtree(entry.path, ignore_errors=True)

    assert caught.value.entry_id == entry.id
    assert caught.value.path == entry.path or caught.value.path.is_relative_to(
        entry.path
    )
    assert (entry.path / MANIFEST_NAME).is_file() or not entry.path.exists()
