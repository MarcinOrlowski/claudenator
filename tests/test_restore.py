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
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from conclaude.core.errors import (
    RestoreClash,
    RestoreFailed,
    TrashEntryDamaged,
    TrashEntryNotFound,
)
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from conclaude.core.trash import MANIFEST_NAME, restore_entry
from tests.fabricate import FakeClaude, encode_project, new_id, snapshot
from tests.test_trash import other_filesystem

PROJECT = "/home/u/dev/app"


def stored_transcript(entry_path: Path, sid: str) -> Path:
    """Where the transcript of a session sits inside an entry."""
    return entry_path / "claude" / "projects" / encode_project(PROJECT) / f"{sid}.jsonl"


def test_every_part_returns_to_where_it_came_from(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """Every part returns to where it came from."""
    sid, other = new_id(), new_id()
    fake.every_part(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    fake.every_part("/home/u/dev/other", other)
    fake.shared()
    before = snapshot(settings.claude_dir)
    entry = store.trash(sid)
    assert snapshot(settings.claude_dir) != before

    restored = store.restore(entry.id)

    assert restored == entry
    assert snapshot(settings.claude_dir) == before
    assert not entry.path.exists()
    assert store.list_trash() == []
    assert store.trash_size() == 0
    assert {session.id for session in store.list_sessions()} == {sid, other}


def test_a_restored_session_has_the_same_data_as_before(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A restored session has the same data as before."""
    sid = new_id()
    fake.every_part(PROJECT, sid)
    [before] = store.list_sessions()

    entry = store.trash(sid)
    assert store.list_sessions() == []
    store.restore(entry.id)

    [after] = store.list_sessions()
    assert after == before
    assert store.details(sid).session == before


def test_an_occupied_place_stops_the_restore_before_anything_moves(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """An occupied place stops the restore before anything moves."""
    sid = new_id()
    parts = fake.every_part(PROJECT, sid)
    entry = store.trash(sid)
    taken = parts["session-env"]
    taken.mkdir()
    (taken / "env").write_bytes(b"NEW=1\n")
    entry_before = snapshot(entry.path)
    claude_before = snapshot(settings.claude_dir)

    with pytest.raises(RestoreClash, match=re.escape(str(taken))) as caught:
        store.restore(entry.id)

    assert caught.value.path == taken
    assert caught.value.entry_id == entry.id
    assert snapshot(entry.path) == entry_before
    assert snapshot(settings.claude_dir) == claude_before
    assert not parts["transcript"].exists()
    assert stored_transcript(entry.path, sid).is_file()
    assert store.list_sessions() == []
    assert [found.id for found in store.list_trash()] == [entry.id]


def test_an_occupied_first_place_stops_the_restore_too(
    fake: FakeClaude, store: SessionStore
) -> None:
    """An occupied first place stops the restore too."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    fake.session_env(sid)
    entry = store.trash(sid)
    path.write_bytes(b"something new\n")

    with pytest.raises(RestoreClash, match=re.escape(str(path))):
        store.restore(entry.id)

    assert path.read_bytes() == b"something new\n"
    assert stored_transcript(entry.path, sid).is_file()
    assert (entry.path / "claude" / "session-env" / sid).is_dir()
    assert not (fake.root / "session-env" / sid).exists()


def test_a_dangling_link_in_the_way_counts_as_occupied(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A dangling link in the way counts as occupied."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    entry = store.trash(sid)
    path.symlink_to(settings.claude_dir.parent / "nowhere")

    with pytest.raises(RestoreClash, match=re.escape(str(path))):
        store.restore(entry.id)

    assert path.is_symlink()
    assert stored_transcript(entry.path, sid).is_file()


def test_a_part_missing_from_the_entry_stops_the_restore(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A part missing from the entry stops the restore."""
    sid = new_id()
    fake.every_part(PROJECT, sid)
    entry = store.trash(sid)
    missing = entry.path / "claude" / "session-env" / sid
    shutil.rmtree(missing)
    before = snapshot(settings.claude_dir)

    with pytest.raises(TrashEntryDamaged, match=re.escape(str(missing))) as caught:
        store.restore(entry.id)

    assert caught.value.path == missing
    assert snapshot(settings.claude_dir) == before
    assert stored_transcript(entry.path, sid).is_file()
    assert [found.id for found in store.list_trash()] == [entry.id]


def test_a_manifest_that_points_outside_is_refused(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A manifest that points outside is refused."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.session_env(sid)
    entry = store.trash(sid)
    manifest = entry.path / MANIFEST_NAME
    good = json.loads(manifest.read_text(encoding="utf-8"))
    outside = settings.claude_dir.parent / "elsewhere"
    (settings.claude_dir.parent / "secret").write_bytes(b"keep out\n")
    before = snapshot(settings.claude_dir.parent)
    bad_originals = [
        str(outside / "env"),
        str(settings.claude_dir / ".." / "elsewhere"),
        str(settings.claude_dir),
        "relative/env",
    ]
    bad_stored = [
        "../../secret",
        "claude/../../secret",
        str(settings.claude_dir.parent / "secret"),
        "session-env/" + sid,
    ]

    for original in bad_originals:
        edited = json.loads(json.dumps(good))
        edited["parts"][1]["original"] = original
        manifest.write_text(json.dumps(edited), encoding="utf-8")
        with pytest.raises(TrashEntryDamaged, match=re.escape(original)):
            store.restore(entry.id)
    for stored in bad_stored:
        edited = json.loads(json.dumps(good))
        edited["parts"][1]["stored"] = stored
        manifest.write_text(json.dumps(edited), encoding="utf-8")
        with pytest.raises(TrashEntryDamaged, match="stored outside the entry"):
            store.restore(entry.id)
    edited = json.loads(json.dumps(good))
    edited["parts"][1]["original"] = edited["parts"][0]["original"]
    manifest.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(TrashEntryDamaged, match="two parts share one place"):
        store.restore(entry.id)

    after = snapshot(settings.claude_dir.parent)
    manifest_key = manifest.relative_to(settings.claude_dir.parent).as_posix()
    assert {key: value for key, value in after.items() if key != manifest_key} == {
        key: value for key, value in before.items() if key != manifest_key
    }
    assert not outside.exists()


def test_the_project_folder_is_made_again_when_it_is_gone(
    fake: FakeClaude, store: SessionStore
) -> None:
    """The project folder is made again when it is gone."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    fake.sidecar(PROJECT, sid)
    entry = store.trash(sid)
    shutil.rmtree(path.parent)

    store.restore(entry.id)

    assert path.is_file()
    assert path.with_suffix("").is_dir()
    assert [session.id for session in store.list_sessions()] == [sid]


def test_a_restored_link_comes_back_as_a_link(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A restored link comes back as a link."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    target = settings.claude_dir.parent / "elsewhere"
    target.mkdir()
    (target / "env").write_bytes(b"A=1\n")
    link = fake.root / "session-env" / sid
    link.symlink_to(target)
    entry = store.trash(sid)
    assert not link.is_symlink()

    store.restore(entry.id)

    assert link.is_symlink()
    assert os.readlink(link) == str(target)
    assert (target / "env").read_bytes() == b"A=1\n"


def test_a_session_can_go_to_the_trash_and_back_more_than_once(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A session can go to the trash and back more than once."""
    sid = new_id()
    fake.every_part(PROJECT, sid)
    [before] = store.list_sessions()

    for _ in range(3):
        entry = store.trash(sid)
        assert store.list_sessions() == []
        store.restore(entry.id)

    [after] = store.list_sessions()
    assert after == before
    assert store.list_trash() == []


def test_restore_finds_an_entry_by_a_prefix_of_the_session_id(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Restore finds an entry by a prefix of the session id."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    entry = store.trash(sid)

    restored = store.restore(sid[:8])

    assert restored.id == entry.id
    assert [session.id for session in store.list_sessions()] == [sid]


def test_restoring_an_unknown_entry_fails(store: SessionStore) -> None:
    """Restoring an unknown entry fails."""
    with pytest.raises(TrashEntryNotFound, match="no Trash entry matches 'nope'"):
        store.restore("nope")


def test_an_entry_gone_between_the_list_and_the_restore_fails_cleanly(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """An entry gone between the list and the restore fails cleanly."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    entry = store.trash(sid)
    SessionStore(settings).purge(entry.id)

    with pytest.raises(TrashEntryNotFound, match=entry.id):
        restore_entry(settings, entry)

    assert store.list_sessions() == []


def test_the_lock_is_held_for_the_whole_restore(
    fake: FakeClaude, settings: Settings
) -> None:
    """The lock is held for the whole restore."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    store = SessionStore(settings)
    entry = store.trash(sid)
    result: list = []

    def run() -> None:
        result.append(store.restore(entry.id))

    with open(settings.trash_lock_file, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(target=run)
        worker.start()
        worker.join(timeout=0.3)
        assert worker.is_alive()
        assert not path.exists()
        assert result == []
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert path.is_file()
    [restored] = result
    assert restored.id == entry.id


def test_a_restore_across_filesystems_copies_then_removes(
    fake: FakeClaude, settings: Settings
) -> None:
    """A restore across filesystems copies then removes."""
    elsewhere = other_filesystem(settings.claude_dir)
    if elsewhere is None:
        pytest.skip("no second filesystem to move to")
    settings.data_dir = Path(tempfile.mkdtemp(prefix="conclaude-", dir=elsewhere))
    try:
        sid = new_id()
        fake.every_part(PROJECT, sid)
        store = SessionStore(settings)
        before = snapshot(settings.claude_dir)
        entry = store.trash(sid)
        assert os.stat(entry.path).st_dev != os.stat(fake.root).st_dev

        store.restore(entry.id)

        assert snapshot(settings.claude_dir) == before
        assert not entry.path.exists()
        assert [session.id for session in store.list_sessions()] == [sid]
    finally:
        shutil.rmtree(settings.data_dir, ignore_errors=True)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_part_that_cannot_move_back_names_the_path(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A part that cannot move back names the path."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    fake.session_env(sid)
    entry = store.trash(sid)
    folder = path.parent
    folder.chmod(0o500)
    try:
        with pytest.raises(RestoreFailed, match=re.escape(str(path))) as caught:
            store.restore(entry.id)
    finally:
        folder.chmod(0o700)

    assert caught.value.path == path
    assert not path.exists()
    assert stored_transcript(entry.path, sid).is_file()
    assert (entry.path / "claude" / "session-env" / sid).is_dir()
    assert [found.id for found in store.list_trash()] == [entry.id]
