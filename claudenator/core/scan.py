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
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from claudenator.core.settings import Settings

SESSION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TRANSCRIPT_SUFFIX = ".jsonl"
PROJECT_KEY = re.compile(r"^[A-Za-z0-9-]+$")
SUBAGENT_DIR = "subagents"


def iter_project_dirs(projects_dir: Path) -> Iterator[Path]:
    """The folders under ``projects/`` that Claude Code could have made."""
    try:
        entries = sorted(os.scandir(projects_dir), key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False) and PROJECT_KEY.match(entry.name):
            yield Path(entry.path)


def iter_transcripts(project_dir: Path) -> Iterator[tuple[str, Path]]:
    """The ``(session id, transcript path)`` pairs inside one project folder."""
    try:
        entries = sorted(os.scandir(project_dir), key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        if not entry.name.endswith(TRANSCRIPT_SUFFIX):
            continue
        session_id = entry.name[: -len(TRANSCRIPT_SUFFIX)]
        if SESSION_ID.match(session_id) and entry.is_file(follow_symlinks=False):
            yield session_id, Path(entry.path)


def sidecar_for(transcript: Path) -> Path | None:
    """The sidecar folder of a transcript, when there is one."""
    candidate = transcript.with_suffix("")
    return candidate if candidate.is_dir() else None


def folder_size(folder: Path) -> int:
    """Bytes held by every file below a folder. Symlinks are not followed."""
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def count_subagents(sidecar: Path | None) -> int:
    """How many subagent transcripts a sidecar holds."""
    if sidecar is None:
        return 0
    try:
        entries = list(os.scandir(sidecar / SUBAGENT_DIR))
    except OSError:
        return 0
    return sum(
        1
        for entry in entries
        if entry.is_file() and entry.name.endswith(TRANSCRIPT_SUFFIX)
    )


@dataclass
class CheapFields:
    """What the cheap read of one transcript found."""

    cwd: str | None = None
    git_branch: str | None = None
    version: str | None = None
    created: datetime | None = None
    custom_title: str | None = None
    human_title: str | None = None
    last_prompt: str | None = None
    fork_parent: str | None = None
    damaged: bool = False


def parse_timestamp(value: Any) -> datetime | None:
    """An Claude timestamp or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def message_text(message: Any) -> str:
    """The text of a message, whether its content is a string or a list of blocks."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def is_human_message(record: dict[str, Any]) -> bool:
    """True for a record that holds a message the user really typed.

    Claude Code marks these with ``origin.kind == "human"``. Injected records
    (caveats, reminders, task notifications) use another "kind" (or none).
    """
    if record.get("type") != "user" or record.get("isMeta"):
        return False
    origin = record.get("origin")
    return isinstance(origin, dict) and origin.get("kind") == "human"


def squash(text: str | None, max_length: int) -> str:
    """One line of text, whitespace collapsed, cut to ``max_length``."""
    if not text:
        return ""
    clean = " ".join(text.split())
    if len(clean) > max_length:
        return clean[: max_length - 3].rstrip() + "..."
    return clean


def derive_title(
    fields: CheapFields,
    session_id: str,
    max_length: int,
    live_name: str | None = None,
) -> tuple[str, str]:
    """The title of a session and where it came from.

    Order: the name in the process marker of a live session, then the last
    custom title, then the first message the user really typed, then the
    pre-truncated copy of the most recent prompt, then the start of the id.
    """
    candidates = (
        ("live", live_name),
        ("custom-title", fields.custom_title),
        ("human", fields.human_title),
        ("last-prompt", fields.last_prompt),
    )
    for source, text in candidates:
        clean = squash(text, max_length)
        if clean:
            return clean, source
    return session_id[:8], "id"


def parse_record(line: bytes) -> dict[str, Any] | None:
    """One line of a transcript as a dict, or None for a line that is not one."""
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _take_meta(record: dict[str, Any], fields: CheapFields) -> bool:
    """Copy cwd, branch, version and timestamp from a record. True once cwd is known."""
    if fields.cwd is None and isinstance(record.get("cwd"), str) and record["cwd"]:
        fields.cwd = record["cwd"]
    if fields.git_branch is None and isinstance(record.get("gitBranch"), str):
        fields.git_branch = record["gitBranch"] or None
    if fields.version is None and isinstance(record.get("version"), str):
        fields.version = record["version"]
    if fields.created is None:
        fields.created = parse_timestamp(record.get("timestamp"))
    return fields.cwd is not None


def _take_fork(record: dict[str, Any], session_id: str, fields: CheapFields) -> bool:
    """Decide fork or not from the first record that carries both id fields."""
    snake = record.get("session_id")
    camel = record.get("sessionId")
    if not (isinstance(snake, str) and isinstance(camel, str)):
        return False
    if snake != camel:
        fields.fork_parent = camel if snake == session_id else snake
    return True


def _read_head(
    transcript: Path, session_id: str, settings: Settings, fields: CheapFields
) -> None:
    seen_meta = seen_human = seen_ids = False
    lines = parsed = 0
    with open(transcript, "rb") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            lines += 1
            record = parse_record(raw)
            if record is not None:
                parsed += 1
                seen_meta = _take_meta(record, fields) or seen_meta
                seen_ids = seen_ids or _take_fork(record, session_id, fields)
                kind = record.get("type")
                if kind == "custom-title" and record.get("customTitle"):
                    fields.custom_title = str(record["customTitle"])
                elif kind == "last-prompt" and record.get("lastPrompt"):
                    fields.last_prompt = str(record["lastPrompt"])
                elif not seen_human and is_human_message(record):
                    fields.human_title = message_text(record.get("message"))
                    seen_human = True
            if (
                seen_meta and seen_human and seen_ids
            ) or lines >= settings.head_records:
                break
    fields.damaged = lines > 0 and parsed == 0


def _read_tail(transcript: Path, settings: Settings, fields: CheapFields) -> None:
    """Find the last custom title and last prompt from a chunk at the end."""
    size = os.path.getsize(transcript)
    want = settings.tail_bytes
    while True:
        start = max(0, size - want)
        with open(transcript, "rb") as handle:
            handle.seek(start)
            chunk = handle.read()
        lines = chunk.split(b"\n")
        if start > 0:
            lines = lines[1:]
        title = prompt = branch = None
        for raw in reversed(lines):
            if not raw.strip():
                continue
            record = parse_record(raw)
            if record is None:
                continue
            kind = record.get("type")
            if title is None and kind == "custom-title" and record.get("customTitle"):
                title = str(record["customTitle"])
            elif prompt is None and kind == "last-prompt" and record.get("lastPrompt"):
                prompt = str(record["lastPrompt"])
            if branch is None and isinstance(record.get("gitBranch"), str):
                branch = record["gitBranch"] or None
            if title is not None and prompt is not None and branch is not None:
                break
        if title is not None:
            fields.custom_title = title
        if prompt is not None:
            fields.last_prompt = prompt
        if branch is not None:
            fields.git_branch = branch
        done = title is not None and prompt is not None
        if done or start == 0 or want >= settings.tail_bytes_max:
            return
        want = min(want * 2, settings.tail_bytes_max)


def read_cheap(transcript: Path, session_id: str, settings: Settings) -> CheapFields:
    """Read the cheap fields of one transcript.

    A few records from the top give cwd, branch, version, creation time, the
    first human message and the fork check. A chunk from the end gives the
    last custom title and the last prompt.
    """
    fields = CheapFields()
    try:
        _read_head(transcript, session_id, settings, fields)
        _read_tail(transcript, settings, fields)
    except OSError:
        fields.damaged = True
    return fields


def _is_foreign(record: dict[str, Any], session_id: str) -> bool:
    snake = record.get("session_id")
    camel = record.get("sessionId")
    return (isinstance(snake, str) and snake != session_id) or (
        isinstance(camel, str) and camel != session_id
    )


def inherited_bytes(transcript: Path, session_id: str) -> int:
    """Bytes of the records a fork copied from its parent.

    Heavy as it reads every line of the transcript. Do not run unless user request
    """
    total = 0
    try:
        with open(transcript, "rb") as handle:
            for raw in handle:
                record = parse_record(raw)
                if record is not None and _is_foreign(record, session_id):
                    total += len(raw)
    except OSError:
        return 0
    return total
