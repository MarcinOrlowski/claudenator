"""Builds a Claude Code data folder in a temporary directory.

Every test drives the store through a ``Settings`` object that points at
folders made here. Nothing is mocked or patched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from conclaude.core.settings import Settings

STARTED = "2026-09-14T07:18:50.439Z"

# What a snapshot records for one path: the kind, then the size and content
# hash for a file, the link target for a symlink, nothing more for a folder.
Snapshot = dict[str, tuple[Any, ...]]


def snapshot(root: Path) -> Snapshot:
    """Every path below a folder, with enough to prove it did not change.

    Symlinks are recorded as links and never followed. Keys are relative to
    ``root`` with ``/`` separators, so two snapshots of different roots can
    be compared part by part.
    """
    found: Snapshot = {}
    if not root.exists():
        return found
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames.sort()
        filenames.sort()
        for name in dirnames + filenames:
            path = here / name
            key = path.relative_to(root).as_posix()
            if path.is_symlink():
                found[key] = ("link", os.readlink(path))
            elif path.is_dir():
                found[key] = ("dir",)
            else:
                data = path.read_bytes()
                found[key] = ("file", len(data), hashlib.sha1(data).hexdigest())
    return found


def encode_project(path: str) -> str:
    """The lossy folder name Claude Code makes from a project path.

    Only the test harness encodes. The tool itself never encodes or decodes.
    """
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def new_id() -> str:
    """A fresh session id."""
    return str(uuid.uuid4())


def dump_line(record: dict[str, Any]) -> bytes:
    """One record as Claude Code writes it: one JSON object, then a newline."""
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


def write_records(path: Path, records: Iterable[dict[str, Any] | bytes]) -> Path:
    """Write records to a transcript.

    A ``bytes`` item is written as it is, so a test can plant a bad line.
    """
    with open(path, "wb") as handle:
        for record in records:
            handle.write(record if isinstance(record, bytes) else dump_line(record))
    return path


def session_records(
    session_id: str,
    cwd: str,
    *,
    human: str | list[dict[str, Any]] | None = "Fix the failing test",
    custom_title: str | None = None,
    last_prompt: str | None = None,
    branch: str | None = "main",
    version: str = "2.1.270",
    started: str = STARTED,
    copied_from: str | None = None,
) -> list[dict[str, Any]]:
    """Records shaped like the ones Claude Code writes, in the order it writes them.

    The first two message records are injected boilerplate, as in a real
    transcript. The human message comes after them. With ``copied_from`` set,
    every message record carries the parent's id in ``session_id``, which is
    how a fork looks on the disk.
    """
    ids = {"sessionId": session_id, "session_id": copied_from or session_id}
    meta = {
        "cwd": cwd,
        "gitBranch": branch if branch is not None else "",
        "version": version,
        "userType": "external",
        "entrypoint": "cli",
        "isSidechain": False,
        "timestamp": started,
        **ids,
    }
    caveat, reminder, question, answer = (new_id() for _ in range(4))
    records: list[dict[str, Any]] = []
    if custom_title is not None:
        records.append(
            {
                "type": "custom-title",
                "customTitle": custom_title,
                "sessionId": session_id,
            }
        )
    records += [
        {"type": "mode", "mode": "normal", "sessionId": session_id},
        {
            "type": "permission-mode",
            "permissionMode": "default",
            "sessionId": session_id,
        },
        {
            "type": "file-history-snapshot",
            "messageId": caveat,
            "snapshot": {"trackedFileBackups": {}},
            "isSnapshotUpdate": False,
        },
        {
            "parentUuid": None,
            "isMeta": True,
            "type": "user",
            "uuid": caveat,
            "message": {
                "role": "user",
                "content": "<local-command-caveat>Injected, not typed.</local-command-caveat>",
            },
            **meta,
        },
        {
            "parentUuid": caveat,
            "type": "attachment",
            "uuid": reminder,
            "attachment": {"type": "instructions", "files": []},
            **meta,
        },
    ]
    if human is not None:
        records += [
            {
                "parentUuid": reminder,
                "type": "user",
                "uuid": question,
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": human},
                **meta,
            },
            {
                "parentUuid": question,
                "type": "assistant",
                "uuid": answer,
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-5",
                    "content": [{"type": "text", "text": "Done."}],
                },
                **meta,
            },
        ]
    if last_prompt is not None:
        records.append(
            {
                "type": "last-prompt",
                "lastPrompt": last_prompt,
                "leafUuid": answer,
                "sessionId": session_id,
            }
        )
    return records


class FakeClaude:
    """A Claude Code data folder built from scratch in a temporary directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        for name in (
            "projects",
            "sessions",
            "session-env",
            "file-history",
            "jobs",
            "todos",
        ):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "history.jsonl").touch()

    def project(self, path: str) -> Path:
        """The stored folder for a project path, made on first use."""
        folder = self.root / "projects" / encode_project(path)
        folder.mkdir(exist_ok=True)
        return folder

    def transcript(
        self,
        project_path: str,
        session_id: str,
        records: Iterable[dict[str, Any] | bytes] | None = None,
        *,
        raw: bytes | None = None,
        mtime: float | None = None,
    ) -> Path:
        """Write one transcript. Pass ``records``, or ``raw`` bytes, or nothing for a plain one."""
        path = self.project(project_path) / f"{session_id}.jsonl"
        if raw is not None:
            path.write_bytes(raw)
        else:
            if records is None:
                records = session_records(session_id, project_path)
            write_records(path, records)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def sidecar(
        self,
        project_path: str,
        session_id: str,
        *,
        agents: int = 1,
        bytes_each: int = 100,
    ) -> Path:
        """A sidecar folder with subagent transcripts of a known size."""
        folder = self.project(project_path) / session_id
        agents_dir = folder / "subagents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        for index in range(agents):
            (agents_dir / f"agent-{index:017x}.jsonl").write_bytes(b"x" * bytes_each)
            (agents_dir / f"agent-{index:017x}.meta.json").write_bytes(b"{}")
        return folder

    def history(self, session_id: str, project: str, display: str = "hello") -> None:
        """Append one line to Claude Code's prompt history."""
        record = {
            "display": display,
            "pastedContents": {},
            "timestamp": 1789384077292,
            "project": project,
            "sessionId": session_id,
        }
        with open(self.root / "history.jsonl", "ab") as handle:
            handle.write(dump_line(record))

    def marker(
        self,
        pid: int,
        session_id: str,
        proc_start: int | str,
        *,
        cwd: str = "/tmp",
        name: str | None = None,
    ) -> Path:
        """A process marker, as Claude Code writes under ``sessions/``."""
        record: dict[str, Any] = {
            "pid": pid,
            "sessionId": session_id,
            "cwd": cwd,
            "startedAt": 1789370639496,
            "procStart": str(proc_start),
            "version": "2.1.270",
            "kind": "interactive",
            "entrypoint": "cli",
        }
        if name is not None:
            record["name"] = name
        path = self.root / "sessions" / f"{pid}.json"
        path.write_bytes(dump_line(record))
        return path

    def lost_and_found(self, where: str = "projects") -> Path:
        """A filesystem recovery folder, as found on a separate mount."""
        folder = self.root / where / "lost+found"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    # The small parts of a session. Each is named after the session id the
    # way Claude Code names it, and each holds a little content of its own
    # so a test can tell it apart after a move.

    def _folder(self, where: str, name: str, files: dict[str, bytes]) -> Path:
        folder = self.root / where / name
        folder.mkdir(parents=True, exist_ok=True)
        for file_name, data in files.items():
            path = folder / file_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return folder

    def session_env(self, session_id: str) -> Path:
        """``session-env/<id>/`` with one environment file."""
        return self._folder("session-env", session_id, {"env": b"A=1\n"})

    def file_history(self, session_id: str) -> Path:
        """``file-history/<id>/`` with a couple of edit snapshots."""
        files = {"0f23617936aa125f@v1": b"old\n", "0f23617936aa125f@v2": b"new\n"}
        return self._folder("file-history", session_id, files)

    def job(self, session_id: str) -> Path:
        """``jobs/<first 8>/`` with a state file, beside the shared ``pins.json``."""
        pins = self.root / "jobs" / "pins.json"
        if not pins.exists():
            pins.parent.mkdir(parents=True, exist_ok=True)
            pins.write_bytes(b"[]\n")
        files = {"state.json": b'{"state": "idle"}\n', "tmp/scratch.txt": b"x\n"}
        return self._folder("jobs", session_id[:8], files)

    def task(self, session_id: str) -> Path:
        """``tasks/<id>/`` with two task files."""
        return self._folder("tasks", session_id, {"1.json": b"{}\n", "2.json": b"{}\n"})

    def debug(self, session_id: str) -> Path:
        """``debug/<id>.txt``."""
        folder = self.root / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session_id}.txt"
        path.write_bytes(b"debug log\n")
        return path

    def todo(self, session_id: str) -> Path:
        """``todos/<id>-agent-<id>.json``."""
        folder = self.root / "todos"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session_id}-agent-{session_id}.json"
        path.write_bytes(b"[]\n")
        return path

    def telemetry(self, session_id: str, event_id: str = "e1") -> Path:
        """``telemetry/1p_failed_events.<id>.<event>.json``."""
        folder = self.root / "telemetry"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"1p_failed_events.{session_id}.{event_id}.json"
        path.write_bytes(b"{}\n")
        return path

    def team(self, session_id: str) -> Path:
        """``teams/<id>/`` with a config file."""
        return self._folder("teams", session_id, {"config.json": b"{}\n"})

    def every_part(self, project_path: str, session_id: str) -> dict[str, Path]:
        """A session with every optional part present, keyed by kind."""
        return {
            "transcript": self.transcript(project_path, session_id),
            "sidecar": self.sidecar(project_path, session_id, agents=2),
            "session-env": self.session_env(session_id),
            "file-history": self.file_history(session_id),
            "job": self.job(session_id),
            "task": self.task(session_id),
            "debug": self.debug(session_id),
            "team": self.team(session_id),
            "todo": self.todo(session_id),
            "telemetry": self.telemetry(session_id),
        }

    def shared(self) -> list[Path]:
        """The files Claude Code shares between sessions. None may ever move.

        The top-level configuration file sits beside the data folder, as
        ``~/.claude.json`` sits beside ``~/.claude``.
        """
        config = self.root.parent / f"{self.root.name}.json"
        config.write_bytes(b'{"theme": "dark"}\n')
        paths = [
            config,
            self.root / "history.jsonl",
            self.root / "settings.json",
            self.root / "paste-cache" / "0123abcd.txt",
            self.root / "plans" / "wise-plan.md",
            self.root / "shell-snapshots" / "snapshot-bash-1789370589613-382iow.sh",
            self.root / "jobs" / "pins.json",
        ]
        for path in paths[1:]:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.stat().st_size == 0:
                path.write_bytes(f"shared {path.name}\n".encode())
        return paths


class FakeProc:
    """A ``/proc`` tree with only the status files the tool reads."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def stat(self, pid: int, start_time: int, comm: str = "claude") -> Path:
        """Write ``<pid>/stat`` with the process start time in field 22."""
        fields = [
            str(pid),
            f"({comm})",
            "S",
            "1",
            str(pid),
            str(pid),
            "0",
            "-1",
            "4194304",
        ]
        fields += ["0"] * 12
        fields.append(str(start_time))
        fields += ["0"] * 30
        folder = self.root / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "stat"
        path.write_text(" ".join(fields) + "\n", encoding="ascii")
        return path


def make_settings(tmp_path: Path) -> Settings:
    """Settings that point every root at the temporary directory."""
    return Settings(
        claude_dir=tmp_path / "claude",
        data_dir=tmp_path / "data",
        proc_dir=tmp_path / "proc",
    )
