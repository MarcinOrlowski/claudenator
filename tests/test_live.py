"""Liveness, driven through a fabricated process table. Nothing is stubbed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conclaude.core.live import find_live, parse_start_time, process_start_time
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from tests.fabricate import FakeClaude, FakeProc, new_id, session_records

PROJECT = "/home/u/dev/app"


def test_a_marker_with_a_matching_process_is_live(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A marker with a matching process is live."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 36917)

    [session] = store.list_sessions()

    assert session.live
    assert session.pid == 4242


def test_a_marker_whose_process_is_gone_is_not_live(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A marker whose process is gone is not live."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.marker(4242, sid, 36917)

    [session] = store.list_sessions()

    assert not session.live
    assert session.pid is None


def test_a_marker_whose_pid_was_reused_is_not_live(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A marker whose pid was reused is not live."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 99001, comm="bash")

    [session] = store.list_sessions()

    assert not session.live


def test_a_live_name_beats_every_other_title(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A live name beats every other title."""
    sid = new_id()
    records = session_records(
        sid, PROJECT, custom_title="Custom", last_prompt="Last", human="Typed"
    )
    fake.transcript(PROJECT, sid, records)
    fake.marker(4242, sid, 36917, name="dev:app-pts3")
    proc.stat(4242, 36917)

    [session] = store.list_sessions()

    assert session.title == "dev:app-pts3"
    assert session.title_source == "live"


def test_a_dead_marker_lends_no_name(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A dead marker lends no name."""
    sid = new_id()
    fake.transcript(PROJECT, sid, session_records(sid, PROJECT, custom_title="Custom"))
    fake.marker(4242, sid, 36917, name="dev:app-pts3")

    [session] = store.list_sessions()

    assert session.title == "Custom"
    assert session.title_source == "custom-title"


def test_a_live_session_without_a_name_keeps_its_title(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """A live session without a name keeps its title."""
    sid = new_id()
    fake.transcript(PROJECT, sid, session_records(sid, PROJECT, custom_title="Custom"))
    fake.marker(4242, sid, 36917, name="   ")
    proc.stat(4242, 36917)

    [session] = store.list_sessions()

    assert session.live
    assert session.title == "Custom"
    assert session.title_source == "custom-title"


def test_liveness_is_checked_afresh_on_every_call(
    fake: FakeClaude, proc: FakeProc, store: SessionStore
) -> None:
    """Liveness is checked afresh on every call."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    stat = proc.stat(4242, 36917)
    assert store.list_sessions()[0].live

    stat.unlink()

    assert not store.list_sessions()[0].live


def test_only_pid_json_files_are_markers(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """Only pid json files are markers."""
    sid = new_id()
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 36917)
    (fake.root / "sessions" / "4242.abc123.key").write_bytes(b"secret")
    (fake.root / "sessions" / "notes.json").write_bytes(b'{"sessionId": "x"}')
    fake.lost_and_found("sessions")

    live = find_live(settings)

    assert set(live) == {sid}
    assert live[sid].marker_path == fake.root / "sessions" / "4242.json"


def test_a_broken_or_incomplete_marker_is_ignored(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """A broken or incomplete marker is ignored."""
    sessions = fake.root / "sessions"
    (sessions / "1.json").write_bytes(b"{not json")
    (sessions / "2.json").write_bytes(b'{"pid": 2, "procStart": "5"}')
    (sessions / "3.json").write_bytes(b'{"pid": 3, "sessionId": "abc"}')
    (sessions / "4.json").write_bytes(
        b'{"pid": 4, "sessionId": "abc", "procStart": "x"}'
    )
    (sessions / "5.json").write_bytes(b'["a", "list"]')
    for pid in (1, 2, 3, 4, 5):
        proc.stat(pid, 5)

    assert find_live(settings) == {}


def test_the_pid_in_the_marker_wins_over_the_file_name(
    fake: FakeClaude, proc: FakeProc, settings: Settings
) -> None:
    """The pid in the marker wins over the file name."""
    sid = new_id()
    path = fake.marker(4242, sid, 36917)
    path.rename(path.with_name("9.json"))
    proc.stat(4242, 36917)

    live = find_live(settings)

    assert live[sid].pid == 4242


def test_a_process_name_with_spaces_and_parentheses_still_parses() -> None:
    """A process name with spaces and parentheses still parses."""
    fields = (
        ["S", "1", "2", "2", "0", "-1", "4194304"] + ["0"] * 12 + ["777"] + ["0"] * 3
    )
    stat = "4242 (claude (dev) x) " + " ".join(fields) + "\n"

    assert parse_start_time(stat) == 777


def test_a_short_or_odd_stat_gives_no_start_time() -> None:
    """A short or odd stat gives no start time."""
    assert parse_start_time("") is None
    assert parse_start_time("4242 (claude) S 1 2\n") is None
    assert parse_start_time("4242 claude S 1 2\n") is None
    assert parse_start_time("4242 (claude) " + " ".join(["z"] * 30)) is None


def test_the_real_process_table_reports_this_test_as_live(tmp_path: Path) -> None:
    """The real process table reports this test as live."""
    settings = Settings(claude_dir=tmp_path, data_dir=tmp_path, proc_dir=Path("/proc"))
    if not (settings.proc_dir / str(os.getpid()) / "stat").exists():
        pytest.skip("no /proc on this platform")
    real = process_start_time(settings.proc_dir, os.getpid())
    assert real is not None

    fake = FakeClaude(settings.claude_dir)
    sid = new_id()
    fake.marker(os.getpid(), sid, real)
    fake.marker(os.getpid() + 1_000_000, new_id(), real)

    assert set(find_live(settings)) == {sid}
