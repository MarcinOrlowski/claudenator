"""Builds a Claude Code data folder in a temporary directory.

Every test drives the store through a ``Settings`` object that points at
folders made here. Nothing is mocked or patched.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from conclaude.core.settings import Settings

STARTED = "2026-09-14T07:18:50.439Z"


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
