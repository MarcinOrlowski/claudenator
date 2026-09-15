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

import json
import re

import pytest

from claudenator.cli.main import main
from claudenator.core.settings import Settings
from claudenator.core.store import SessionStore
from tests.fabricate import (
    FakeClaude,
    FakeProc,
    answer_records,
    dump_line,
    new_id,
    prompt_record,
    session_records,
)

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
    assert lines[0].split() == ["ID", "STS", "LAST", "USED", "SIZE", "TITLE", "PROJECT"]
    assert lines[1].startswith(sid[:8])
    # The default time format is relative, and the transcript was written just now
    assert re.search(r"just now|\d+s ago", lines[1])
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
    states = {sid[:8]: rows[sid[:8]].split()[1] for sid in (parent, child, broken)}
    assert states == {parent[:8]: "---", child[:8]: "-F-", broken[:8]: "--D"}


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
    assert "dev:app-pts3" in rows[running[:8]]
    assert rows[running[:8]].split()[1] == "L--"
    assert "B" in rows[stale[:8]]
    assert rows[stale[:8]].split()[1] == "---"
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


def test_no_command_opens_the_screen(
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No command opens the screen."""
    opened: list[Settings] = []
    monkeypatch.setattr(
        "claudenator.cli.main.open_screen",
        lambda settings: opened.append(settings) or 0,
    )

    code, out, _err = run(capsys, settings)

    assert code == 0
    assert out == ""
    assert [given.claude_dir for given in opened] == [settings.claude_dir]
    assert opened[0].data_dir == settings.data_dir


def test_help_flag_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Help flag prints help."""
    with pytest.raises(SystemExit) as stop:
        main(["--help"])
    out, _err = capsys.readouterr()
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)

    assert stop.value.code == 0
    assert plain.startswith("usage: claudenator")


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Version flag."""
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    out, _err = capsys.readouterr()

    assert stop.value.code == 0
    assert out.startswith("claudenator ")


def test_scan_reads_every_session_once_and_then_uses_the_cache(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first scan reads every transcript. The second finds them all fresh and
    reads none. ``--force`` reads them again. One line per session, then a sum.
    """
    one, two = new_id(), new_id()
    fake.transcript(
        PROJECT,
        one,
        session_records(one, PROJECT) + answer_records(one, tools=["Bash"]),
    )
    fake.transcript(PROJECT, two, session_records(two, PROJECT, human=None))

    code, first, err = run(capsys, settings, "scan")
    _code, second, _err = run(capsys, settings, "scan")
    _code, forced, _err = run(capsys, settings, "scan", "--force")

    assert code == 0 and err == ""
    rows = {
        line[:8]: line for line in first.splitlines() if line[:8] in (one[:8], two[:8])
    }
    assert rows[one[:8]].endswith("1 turn  370 tokens  0s  scanned")
    assert rows[two[:8]].endswith("0 turns  0 tokens  0s  scanned")
    assert "2 scanned, 0 already fresh, 0 failed, 0 gone from the disk" in first
    assert first.rstrip().endswith(f"Cache: {settings.cache_file}")
    assert second.count("  cached") == 2
    assert "0 scanned, 2 already fresh" in second
    assert forced.count("  scanned") == 2
    assert settings.cache_file.is_file()


def test_scan_with_nothing_to_scan(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scan with nothing to scan says so and makes no cache."""
    code, out, _err = run(capsys, settings, "scan")

    assert code == 0
    assert out.startswith("No sessions found under ")
    assert not settings.cache_file.exists()


def test_scan_reports_a_transcript_it_cannot_read_and_goes_on(
    fake: FakeClaude,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unreadable transcript is named on stderr. The rest are scanned. Exit 1."""
    bad, good = new_id(), new_id()
    bad_path = fake.transcript(PROJECT, bad)
    fake.transcript(PROJECT, good)
    from claudenator.core import store as store_module

    real = store_module.deep_scan

    def flaky(path, *args, **kwargs):
        if path == bad_path:
            raise PermissionError(13, "Permission denied")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "deep_scan", flaky)

    code, out, err = run(capsys, settings, "scan")

    assert code == 1
    assert f"{bad[:8]}  could not read {bad_path}: Permission denied" in err
    assert good[:8] in out
    assert "1 scanned, 0 already fresh, 1 failed" in out


def test_scan_forgets_the_figures_of_a_trashed_session(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """A scan drops the row of a transcript that left the disk, and says so."""
    gone, kept = new_id(), new_id()
    fake.transcript(PROJECT, gone)
    fake.transcript(PROJECT, kept)
    run(capsys, settings, "scan")
    SessionStore(settings).trash(gone)

    _code, out, _err = run(capsys, settings, "scan")

    assert "0 scanned, 1 already fresh, 0 failed, 1 gone from the disk" in out


def test_info_shows_the_figures_after_a_scan_and_marks_them_when_stale(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before a scan, info names the command to run. After it, the figures show.
    After the transcript changes, the old figures stay, each marked outdated.
    """
    sid = new_id()
    records = session_records(sid, PROJECT) + answer_records(
        sid, tools=["Bash", "Edit"]
    )
    path = fake.transcript(PROJECT, sid, records)

    _code, before, _err = run(capsys, settings, "info", sid)
    run(capsys, settings, "scan")
    _code, after, _err = run(capsys, settings, "info", sid)
    with open(path, "ab") as handle:
        handle.write(dump_line(prompt_record(sid, "One more thing")))
    code, stale, _err = run(capsys, settings, "info", sid)

    assert "Deep scan:   none  (run 'claudenator scan')" in before
    assert "Turns:" not in before
    assert "Turns:        1\n" in after
    assert "Tokens:       370  (10 in, 20 out)\n" in after
    assert "Cache tokens: 300 read, 40 written\n" in after
    assert "Models:       claude-opus-5 (2)\n" in after
    assert "Tool calls:   2  (Bash 1, Edit 1)\n" in after
    # The details always name the moment and how long ago it was.
    assert re.search(
        r"Scanned:      \d{4}-\d\d-\d\d \d\d:\d\d:\d\d \((just now|\d+s ago)\)\n", after
    )
    assert code == 0
    assert "Turns:        (outdated) 1\n" in stale
    assert "Tokens:       (outdated) 370  (10 in, 20 out)\n" in stale
    assert "Tool calls:   (outdated) 2  (Bash 1, Edit 1)\n" in stale
    assert "(the transcript changed since; run 'claudenator scan')" in stale


def test_info_json_carries_the_figures_or_null(
    fake: FakeClaude, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON form has ``figures`` as null before a scan and as an object after."""
    sid = new_id()
    path = fake.transcript(
        PROJECT, sid, session_records(sid, PROJECT) + answer_records(sid)
    )

    _code, before, _err = run(capsys, settings, "info", sid, "--json")
    run(capsys, settings, "scan")
    _code, after, _err = run(capsys, settings, "info", sid, "--json")
    path.write_bytes(path.read_bytes() + b"\n")
    _code, changed, _err = run(capsys, settings, "info", sid, "--json")

    assert json.loads(before)["figures"] is None
    figures = json.loads(after)["figures"]
    assert figures["stale"] is False
    assert figures["turns"] == 1
    assert figures["tokens"] == 370
    assert figures["models"] == {"claude-opus-5": 2}
    assert json.loads(changed)["figures"]["stale"] is True
    assert json.loads(changed)["figures"]["turns"] == 1
