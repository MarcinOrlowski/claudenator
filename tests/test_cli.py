"""The command line, driven through ``main`` against a fake folder."""

from __future__ import annotations

import json
import re

import pytest

from conclaude.cli.main import main
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from tests.fabricate import FakeClaude, FakeProc, new_id, session_records

PROJECT = "/p/x"


def run(
    capsys: pytest.CaptureFixture[str], settings: Settings, *argv: str
) -> tuple[int, str, str]:
    """Run the command against the fake folders and capture what it printed."""
    roots = [
        "--claude-dir",
        str(settings.claude_dir),
        "--data-dir",
        str(settings.data_dir),
        "--proc-dir",
        str(settings.proc_dir),
    ]
    code = main([*roots, *argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_list_json(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """List json."""
    sid = new_id()
    fake.transcript(PROJECT, sid, session_records(sid, PROJECT, custom_title="Hello"))
    fake.sidecar(PROJECT, sid, bytes_each=10)

    code, out, _err = run(capsys, settings, "list", "--json")

    assert code == 0
    [row] = json.loads(out)
    assert row["id"] == sid
    assert row["title"] == "Hello"
    assert row["project_path"] == PROJECT
    assert row["sidecar_size"] == 10 + len(b"{}")
    assert row["size"] == row["transcript_size"] + row["sidecar_size"]
    assert row["last_used"].endswith("+00:00")
    assert "." not in row["last_used"]
    assert row["created"] == "2026-09-14T07:18:50+00:00"


def test_list_table(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """List table."""
    sid = new_id()
    fake.transcript(PROJECT, sid, session_records(sid, PROJECT, custom_title="Hello"))

    code, out, _err = run(capsys, settings, "list")

    lines = out.splitlines()
    assert code == 0
    assert lines[0].split() == ["ID", "LAST", "USED", "SIZE", "TITLE", "PROJECT"]
    assert lines[1].startswith(sid[:8])
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", lines[1])
    assert "Hello" in lines[1]
    assert lines[1].endswith(PROJECT)
    assert lines[-1].startswith("1 session,")


def test_list_marks_forks_and_damage(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """List marks forks and damage."""
    parent, child, broken = new_id(), new_id(), new_id()
    fake.transcript(PROJECT, parent)
    fake.transcript(
        PROJECT,
        child,
        session_records(child, PROJECT, copied_from=parent, custom_title="Kid"),
    )
    fake.transcript(PROJECT, broken, raw=b"\xff\xfe")

    _code, out, _err = run(capsys, settings, "list")

    rows = {line[:8]: line for line in out.splitlines()[1:] if line.strip()}
    assert "[fork]" in rows[child[:8]]
    assert "[damaged]" in rows[broken[:8]]
    assert "[" not in rows[parent[:8]].split("  ", 3)[3].split(PROJECT)[0]


def test_list_marks_live_sessions_and_uses_their_name(
    fake: FakeClaude,
    proc: FakeProc,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """List marks live sessions and uses their name."""
    running, stale = new_id(), new_id()
    fake.transcript(
        PROJECT, running, session_records(running, PROJECT, custom_title="A")
    )
    fake.transcript(PROJECT, stale, session_records(stale, PROJECT, custom_title="B"))
    fake.marker(100, running, 5000, name="dev:app-pts3")
    fake.marker(200, stale, 6000, name="gone")
    proc.stat(100, 5000)
    proc.stat(200, 6001)

    _code, out, _err = run(capsys, settings, "list")
    _code, json_out, _err = run(capsys, settings, "list", "--json")

    rows = {line[:8]: line for line in out.splitlines()[1:] if line.strip()}
    assert "dev:app-pts3 [live]" in rows[running[:8]]
    assert "B" in rows[stale[:8]]
    assert "[live]" not in rows[stale[:8]]
    by_id = {row["id"]: row for row in json.loads(json_out)}
    assert by_id[running]["live"] is True
    assert by_id[running]["pid"] == 100
    assert by_id[running]["title_source"] == "live"
    assert by_id[stale]["live"] is False
    assert by_id[stale]["pid"] is None


def test_info_shows_the_pid_of_a_live_session(
    fake: FakeClaude,
    proc: FakeProc,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Info shows the pid of a live session."""
    sid = new_id()
    fake.transcript(PROJECT, sid)
    fake.marker(4242, sid, 36917)
    proc.stat(4242, 36917)

    code, out, _err = run(capsys, settings, "info", sid)

    assert code == 0
    assert "Live:        yes  (pid 4242)" in out


def test_list_no_longer_shows_a_trashed_session(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """List no longer shows a trashed session."""
    gone, kept = new_id(), new_id()
    fake.transcript(PROJECT, gone, session_records(gone, PROJECT, custom_title="Gone"))
    fake.transcript(PROJECT, kept, session_records(kept, PROJECT, custom_title="Kept"))
    SessionStore(settings).trash(gone)

    code, out, _err = run(capsys, settings, "list")
    _code, json_out, _err = run(capsys, settings, "list", "--json")
    _code, _out, err = run(capsys, settings, "info", gone)

    assert code == 0
    assert "Kept" in out
    assert "Gone" not in out
    assert [row["id"] for row in json.loads(json_out)] == [kept]
    assert f"no session matches '{gone}'" in err


def test_list_shows_a_restored_session_with_the_same_data(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """List shows a restored session with the same data."""
    sid = new_id()
    fake.every_part(PROJECT, sid)
    _code, before, _err = run(capsys, settings, "list", "--json")
    _code, info_before, _err = run(capsys, settings, "info", sid, "--json")
    store = SessionStore(settings)
    entry = store.trash(sid)
    _code, gone, _err = run(capsys, settings, "list", "--json")

    store.restore(entry.id)
    code, after, _err = run(capsys, settings, "list", "--json")
    _code, info_after, _err = run(capsys, settings, "info", sid, "--json")

    assert code == 0
    assert json.loads(gone) == []
    assert json.loads(after) == json.loads(before)
    assert json.loads(info_after) == json.loads(info_before)


def test_list_with_nothing_to_show(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """List with nothing to show."""
    code, out, _err = run(capsys, settings, "list")

    assert code == 0
    assert out.startswith("No sessions found under ")


def test_info_by_prefix(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Info by prefix."""
    sid = new_id()
    fake.transcript(
        PROJECT, sid, session_records(sid, PROJECT, custom_title="Hello", branch="dev")
    )
    fake.sidecar(PROJECT, sid, agents=3)

    code, out, _err = run(capsys, settings, "info", sid[:8])

    assert code == 0
    assert f"Id:          {sid}" in out
    assert "Title:       Hello  (from custom-title)" in out
    assert f"Project:     {PROJECT}  (from transcript)" in out
    assert "Git branch:  dev" in out
    assert "Claude Code: 2.1.270" in out
    assert "(3 subagent transcripts)" in out
    assert "Fork of:" not in out
    assert "Damaged:     no" in out


def test_info_of_a_fork_shows_the_inherited_bytes(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Info of a fork shows the inherited bytes."""
    parent, child = new_id(), new_id()
    fake.transcript(PROJECT, parent)
    fake.transcript(PROJECT, child, session_records(child, PROJECT, copied_from=parent))

    code, out, _err = run(capsys, settings, "info", child)

    assert code == 0
    assert f"Fork of:     {parent}" in out
    assert "came from the parent" in out


def test_info_json(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Info json."""
    sid = new_id()
    fake.transcript(PROJECT, sid)

    code, out, _err = run(capsys, settings, "info", sid, "--json")

    assert code == 0
    data = json.loads(out)
    assert data["id"] == sid
    assert data["inherited_bytes"] == 0
    assert data["fork_parent"] is None


def test_info_of_an_unknown_id_fails(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Info of an unknown id fails."""
    code, out, err = run(capsys, settings, "info", "nope")

    assert code == 1
    assert out == ""
    assert "no session matches 'nope'" in err


def test_info_with_an_ambiguous_prefix_fails(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Info with an ambiguous prefix fails."""
    fake.transcript(PROJECT, "abcdef00-0000-4000-8000-000000000001")
    fake.transcript(PROJECT, "abcdef00-0000-4000-8000-000000000002")

    code, _out, err = run(capsys, settings, "info", "abcdef")

    assert code == 1
    assert "'abcdef' matches 2 sessions" in err


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    """No command prints help."""
    code = main([])
    out, _err = capsys.readouterr()
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)

    assert code == 0
    assert plain.startswith("usage: conclaude")


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Version flag."""
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    out, _err = capsys.readouterr()

    assert stop.value.code == 0
    assert out.startswith("conclaude ")
