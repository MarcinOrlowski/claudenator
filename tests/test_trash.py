"""
##################################################################################
#
# Claudenator by Marcin Orlowski
# The only Claude Code session manager you need.
#
# @author    Marcin Orlowski <mail@marcinOrlowski.com>
# Copyright  ©2026 Marcin Orlowski <MarcinOrlowski.com>
# @link      https://github.com/MarcinOrlowski/claudenator
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
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claudenator.core.errors import SessionIsLive, SessionNotFound, TrashFailed
from claudenator.core.settings import Settings
from claudenator.core.store import SessionStore
from claudenator.core.trash import (
    MANIFEST_NAME,
    copy_then_remove,
    find_parts,
    trash_session,
)
from tests.fabricate import (
    FakeClaude,
    FakeProc,
    encode_project,
    new_id,
    snapshot,
)

PROJECT = "/home/u/dev/app"
ENTRY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_[0-9a-f-]{36}$")


def test_every_part_moves_into_one_entry(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """Every part moves into one entry."""
    sid = new_id()
    parts = fake.every_part(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    parts["marker"] = fake.root / "sessions" / "4242.json"
    before = {kind: snapshot(path) for kind, path in parts.items()}
    contents = {
        kind: path.read_bytes() for kind, path in parts.items() if path.is_file()
    }

    entry = store.trash(sid)

    assert ENTRY_NAME.match(entry.id)
    assert entry.path == settings.trash_dir / entry.id
    assert entry.session_id == sid
    assert entry.title == "Fix the failing test"
    assert entry.project_path == PROJECT
    assert entry.trashed_at.tzinfo is not None
    assert entry.trashed_at.microsecond == 0
    assert {part.kind for part in entry.parts} == set(parts)
    for kind, original in parts.items():
        assert not original.exists() and not original.is_symlink(), kind
        stored = entry.path / "claude" / original.relative_to(fake.root)
        assert stored.exists(), kind
        if kind in contents:
            assert stored.read_bytes() == contents[kind], kind
        else:
            assert snapshot(stored) == before[kind], kind
    assert store.list_sessions() == []


def test_the_manifest_records_where_every_part_belongs(
    fake: FakeClaude, store: SessionStore
) -> None:
    """The manifest records where every part belongs."""
    sid = new_id()
    parts = fake.every_part(PROJECT, sid)
    was_dir = {kind: path.is_dir() for kind, path in parts.items()}
    transcript_size = parts["transcript"].stat().st_size

    entry = store.trash(sid)
    manifest = json.loads((entry.path / MANIFEST_NAME).read_text(encoding="utf-8"))

    assert manifest["version"] == 1
    assert manifest["session_id"] == sid
    assert manifest["title"] == "Fix the failing test"
    assert manifest["project_path"] == PROJECT
    assert manifest["trashed_at"] == entry.trashed_at.isoformat(timespec="seconds")
    assert "." not in manifest["trashed_at"]
    assert manifest["size"] == entry.size > 0
    by_kind = {part["kind"]: part for part in manifest["parts"]}
    assert set(by_kind) == set(parts)
    for kind, original in parts.items():
        assert by_kind[kind]["original"] == str(original)
        assert (entry.path / by_kind[kind]["stored"]).exists()
        assert by_kind[kind]["type"] == ("dir" if was_dir[kind] else "file")
    assert by_kind["transcript"]["size"] == transcript_size
    assert by_kind["sidecar"]["size"] == 2 * 100 + 2 * len(b"{}")
    assert manifest["size"] == sum(part["size"] for part in manifest["parts"])


def test_a_session_with_only_a_transcript_trashes_cleanly(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A session with only a transcript trashes cleanly."""
    sid = new_id()
    fake.transcript(PROJECT, sid)

    entry = store.trash(sid)

    assert [part.kind for part in entry.parts] == ["transcript"]
    assert store.list_sessions() == []
    assert (entry.path / MANIFEST_NAME).is_file()


def test_the_entry_keeps_the_folder_shape_and_reads_with_plain_tools(
    fake: FakeClaude, store: SessionStore
) -> None:
    """The entry keeps the folder shape and reads with plain tools."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.sidecar(PROJECT, sid, agents=1)
    fake.session_env(sid)
    key = encode_project(PROJECT)

    entry = store.trash(sid)

    found = sorted(
        path.relative_to(entry.path).as_posix()
        for path in entry.path.rglob("*")
        if path.is_file()
    )
    assert found == [
        f"claude/projects/{key}/{sid}.jsonl",
        f"claude/projects/{key}/{sid}/subagents/agent-00000000000000000.jsonl",
        f"claude/projects/{key}/{sid}/subagents/agent-00000000000000000.meta.json",
        f"claude/session-env/{sid}/env",
        MANIFEST_NAME,
    ]


def test_nothing_shared_and_nothing_outside_is_touched(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """Nothing shared and nothing outside is touched."""
    sid, other = new_id(), new_id()
    fake.every_part(PROJECT, sid)
    fake.every_part("/home/u/dev/other", other)
    fake.history(sid, PROJECT)
    fake.shared()
    fake.marker(7, other, 1000)
    fake.lost_and_found("todos")
    outside = settings.claude_dir.parent / "elsewhere"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"mine\n")
    (settings.claude_dir.parent / "keep.txt").write_bytes(b"mine too\n")
    parts = find_parts(settings, store.find_session(sid))
    moved = {
        part.original.relative_to(settings.claude_dir).as_posix() for part in parts
    }
    whole_before = snapshot(settings.claude_dir.parent)

    store.trash(sid)

    whole_after = snapshot(settings.claude_dir.parent)
    claude = settings.claude_dir.relative_to(settings.claude_dir.parent).as_posix()
    data = settings.data_dir.relative_to(settings.claude_dir.parent).as_posix()
    for key, value in whole_before.items():
        inside = (
            key.removeprefix(claude + "/") if key.startswith(claude + "/") else None
        )
        if inside is not None and any(
            inside == part or inside.startswith(part + "/") for part in moved
        ):
            assert key not in whole_after, key
        else:
            assert whole_after.get(key) == value, key
    for key in whole_after:
        assert key in whole_before or key.startswith(data), key


def test_the_project_folder_stays_when_its_last_session_goes(
    fake: FakeClaude, store: SessionStore
) -> None:
    """The project folder stays when its last session goes."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    folder = fake.project(PROJECT)
    (folder / "memory" / "MEMORY.md").parent.mkdir()
    (folder / "memory" / "MEMORY.md").write_text("keep me")

    store.trash(sid)

    assert folder.is_dir()
    assert (folder / "memory" / "MEMORY.md").read_text() == "keep me"
    assert store.list_projects() == []


def test_a_live_session_cannot_be_trashed(
    fake: FakeClaude, proc: FakeProc, store: SessionStore, settings: Settings
) -> None:
    """A live session cannot be trashed."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 36917)

    with pytest.raises(SessionIsLive, match=f"session {sid[:8]} is live .pid 4242."):
        store.trash(sid)

    assert path.is_file()
    assert not settings.trash_dir.exists() or list(settings.trash_dir.iterdir()) == []
    assert [session.id for session in store.list_sessions()] == [sid]


def test_liveness_is_checked_again_at_the_moment_of_the_move(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """Liveness is checked again at the moment of the move."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    [session] = SessionStore(settings).list_sessions()
    assert not session.live
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 36917)

    with pytest.raises(SessionIsLive):
        trash_session(settings, session)


def test_a_stale_marker_travels_and_a_foreign_one_stays(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A stale marker travels and a foreign one stays."""
    sid, other = new_id(), new_id()
    fake.transcript(PROJECT, sid)
    fake.transcript(PROJECT, other)
    stale = fake.marker(100, sid, 5000)
    foreign = fake.marker(200, other, 6000)
    proc.stat(200, 6000)
    key = fake.root / "sessions" / "100.abc.key"
    key.write_bytes(b"secret")

    entry = store.trash(sid)

    assert not stale.exists()
    assert (entry.path / "claude" / "sessions" / "100.json").is_file()
    assert foreign.is_file()
    assert key.is_file()
    assert [part.kind for part in entry.parts] == ["transcript", "marker"]


def test_only_things_named_after_this_session_move(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Only things named after this session move."""
    sid, other = new_id(), new_id()
    fake.transcript(PROJECT, sid)
    fake.transcript(PROJECT, other)
    fake.todo(sid)
    theirs = fake.todo(other)
    fake.telemetry(sid, "e1")
    fake.telemetry(sid, "e2")
    theirs_too = fake.telemetry(other)
    fake.lost_and_found("todos")
    fake.lost_and_found("telemetry")
    their_env = fake.session_env(other)
    their_job = fake.job(other)

    entry = store.trash(sid)

    kinds = [part.kind for part in entry.parts]
    assert kinds == ["transcript", "todo", "telemetry", "telemetry"]
    assert theirs.is_file() and theirs_too.is_file()
    assert their_env.is_dir() and their_job.is_dir()
    assert (fake.root / "todos" / "lost+found").is_dir()
    assert (fake.root / "jobs" / "pins.json").is_file()
    assert [session.id for session in store.list_sessions()] == [other]


def test_a_symlinked_part_moves_as_a_link(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A symlinked part moves as a link."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    target = settings.claude_dir.parent / "elsewhere"
    target.mkdir()
    (target / "env").write_bytes(b"A=1\n")
    link = fake.root / "session-env" / sid
    link.symlink_to(target)

    entry = store.trash(sid)

    stored = entry.path / "claude" / "session-env" / sid
    assert stored.is_symlink()
    assert os.readlink(stored) == str(target)
    assert not link.is_symlink()
    assert (target / "env").read_bytes() == b"A=1\n"
    assert [part.is_dir for part in entry.parts] == [False, False]


def test_the_entry_id_never_reuses_a_folder(
    fake: FakeClaude, settings: Settings
) -> None:
    """The entry id never reuses a folder."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    store = SessionStore(settings)
    moment = datetime(2026, 9, 14, 10, 8, 33, tzinfo=timezone.utc)
    expected = moment.astimezone().strftime("%Y-%m-%dT%H-%M-%S") + "_" + sid
    (settings.trash_dir / expected).mkdir(parents=True)
    (settings.trash_dir / f"{expected}-2").mkdir()

    entry = trash_session(settings, store.find_session(sid), now=moment)

    assert entry.id == f"{expected}-3"
    assert entry.path.is_dir()


def test_trash_of_moves_a_session_already_in_hand_and_reads_nothing_again(
    fake: FakeClaude,
    store: SessionStore,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``trash_of`` moves a session already in hand. It reads the list again for nothing."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    [session] = store.list_sessions()
    monkeypatch.setattr(
        store, "list_sessions", lambda: pytest.fail("the session list was read again")
    )

    entry = store.trash_of(session)

    assert entry.session_id == sid
    assert not path.exists()
    assert SessionStore(settings).list_sessions() == []


def test_trashing_an_unknown_id_fails(store: SessionStore) -> None:
    """Trashing an unknown id fails."""
    with pytest.raises(SessionNotFound):
        store.trash("nope")


def test_a_session_gone_between_the_list_and_the_move_fails_cleanly(
    fake: FakeClaude, settings: Settings
) -> None:
    """A session gone between the list and the move fails cleanly."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    [session] = SessionStore(settings).list_sessions()
    path.unlink()

    with pytest.raises(SessionNotFound):
        trash_session(settings, session)

    assert not settings.trash_dir.exists()


def test_the_lock_is_held_for_the_whole_move(
    fake: FakeClaude, settings: Settings
) -> None:
    """The lock is held for the whole move."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    store = SessionStore(settings)
    settings.data_dir.mkdir(parents=True)
    result: list = []

    def run() -> None:
        result.append(store.trash(sid))

    with open(settings.trash_lock_file, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(target=run)
        worker.start()
        worker.join(timeout=0.3)
        assert worker.is_alive()
        assert path.is_file()
        assert result == []
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert not path.exists()
    [entry] = result
    assert entry.session_id == sid


def other_filesystem(near: Path) -> Path | None:
    """A folder on a different filesystem than ``near``, or None if there is none."""
    for candidate in (Path("/dev/shm"), Path(tempfile.gettempdir())):
        try:
            if candidate.is_dir() and os.stat(candidate).st_dev != os.stat(near).st_dev:
                return candidate
        except OSError:
            continue
    return None


def test_a_move_across_filesystems_copies_then_removes(
    fake: FakeClaude, settings: Settings
) -> None:
    """A move across filesystems copies then removes."""
    elsewhere = other_filesystem(settings.claude_dir)
    if elsewhere is None:
        pytest.skip("no second filesystem to move to")
    settings.data_dir = Path(tempfile.mkdtemp(prefix="claudenator-", dir=elsewhere))
    try:
        sid = new_id()
        parts = fake.every_part(PROJECT, sid)
        before = {kind: snapshot(path) for kind, path in parts.items()}
        sizes = {kind: path.stat().st_size for kind, path in parts.items()}

        entry = SessionStore(settings).trash(sid)

        assert entry.path.is_relative_to(settings.data_dir)
        assert os.stat(entry.path).st_dev != os.stat(fake.root).st_dev
        for kind, original in parts.items():
            assert not original.exists(), kind
            stored = entry.path / "claude" / original.relative_to(fake.root)
            if stored.is_dir():
                assert snapshot(stored) == before[kind], kind
            else:
                assert stored.stat().st_size == sizes[kind], kind
        assert SessionStore(settings).list_sessions() == []
    finally:
        shutil.rmtree(settings.data_dir, ignore_errors=True)


def test_copy_then_remove_handles_files_folders_and_links(tmp_path: Path) -> None:
    """Copy then remove handles files folders and links."""
    source = tmp_path / "src"
    (source / "deep").mkdir(parents=True)
    (source / "deep" / "a.txt").write_bytes(b"a")
    (source / "link").symlink_to(tmp_path / "outside")
    (tmp_path / "outside").write_bytes(b"outside")
    (tmp_path / "one.txt").write_bytes(b"one")
    target = tmp_path / "dst"

    copy_then_remove(source, target)
    copy_then_remove(tmp_path / "one.txt", tmp_path / "moved.txt")

    assert not source.exists()
    assert (target / "deep" / "a.txt").read_bytes() == b"a"
    assert (target / "link").is_symlink()
    assert (tmp_path / "outside").read_bytes() == b"outside"
    assert (tmp_path / "moved.txt").read_bytes() == b"one"
    assert not (tmp_path / "one.txt").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_part_that_cannot_move_names_the_path(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """A part that cannot move names the path."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    fake.session_env(sid)
    folder = fake.project(PROJECT)
    folder.chmod(0o500)
    try:
        with pytest.raises(TrashFailed, match=re.escape(str(path))) as caught:
            store.trash(sid)
    finally:
        folder.chmod(0o700)

    assert caught.value.path == path
    assert path.is_file()
    assert (fake.root / "session-env" / sid).is_dir()
    [entry_dir] = settings.trash_dir.iterdir()
    assert (entry_dir / MANIFEST_NAME).is_file()
    assert [session.id for session in store.list_sessions()] == [sid]
