"""Which sessions a Claude Code process is running right now.

Claude Code writes a process marker to ``sessions/<pid>.json`` when it
starts. The marker names the session and records ``procStart``, the start
time of the process as the kernel counts it. A crash leaves the marker
behind, and the pid can be handed to an unrelated process later. So a marker
alone proves nothing. A session is live only when the process named by the
marker exists and its start time in ``/proc/<pid>/stat`` is the one the
marker recorded.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conclaude.core.settings import Settings

MARKER_NAME = re.compile(r"^(\d+)\.json$")

# ``/proc/<pid>/stat`` holds the process name in parentheses as field 2, and
# the name may hold spaces and parentheses of its own. The fields after it
# are numbered from 3. The start time is field 22.
START_TIME_FIELD = 22


@dataclass(frozen=True)
class LiveSession:
    """A session with a running process behind it."""

    session_id: str
    pid: int
    name: str | None
    marker_path: Path


def parse_start_time(stat: str) -> int | None:
    """The process start time out of the text of ``/proc/<pid>/stat``.

    The process name sits in parentheses and may contain spaces, so the
    fields are counted from the last closing parenthesis, not from the start.
    """
    _head, paren, tail = stat.rpartition(")")
    if not paren:
        return None
    rest = tail.split()
    index = START_TIME_FIELD - 3
    if len(rest) <= index:
        return None
    try:
        return int(rest[index])
    except ValueError:
        return None


def process_start_time(proc_dir: Path, pid: int) -> int | None:
    """The start time of a running process, or None when there is no such process."""
    try:
        with open(proc_dir / str(pid) / "stat", "r", encoding="ascii") as handle:
            return parse_start_time(handle.read())
    except (OSError, ValueError):
        return None


def read_marker(path: Path) -> dict[str, Any] | None:
    """One process marker as a dict, or None when it is not one."""
    try:
        with open(path, "rb") as handle:
            record = json.loads(handle.read())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def iter_markers(sessions_dir: Path) -> list[tuple[int, Path]]:
    """Every ``<pid>.json`` under ``sessions/``, with its pid, in name order."""
    found: list[tuple[int, Path]] = []
    try:
        entries = os.scandir(sessions_dir)
    except OSError:
        return found
    with entries:
        for entry in entries:
            match = MARKER_NAME.match(entry.name)
            if match and entry.is_file(follow_symlinks=False):
                found.append((int(match.group(1)), Path(entry.path)))
    found.sort()
    return found


def find_live(settings: Settings) -> dict[str, LiveSession]:
    """Session id to live session, for every marker whose process really runs.

    A marker counts only when the process exists and started when the
    marker says it did. A marker that names no session, no pid, or no start
    time is ignored.
    """
    live: dict[str, LiveSession] = {}
    for pid_from_name, path in iter_markers(settings.sessions_dir):
        record = read_marker(path)
        if record is None:
            continue
        session_id = record.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            continue
        pid = _as_int(record.get("pid"))
        if pid is None:
            pid = pid_from_name
        recorded = _as_int(record.get("procStart"))
        if recorded is None:
            continue
        actual = process_start_time(settings.proc_dir, pid)
        if actual is None or actual != recorded:
            continue
        name = record.get("name")
        if not isinstance(name, str) or not name.strip():
            name = None
        if session_id not in live:
            live[session_id] = LiveSession(
                session_id=session_id, pid=pid, name=name, marker_path=path
            )
    return live
