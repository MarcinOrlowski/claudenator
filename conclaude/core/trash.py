"""Move a session to the Trash.

CC writes its parts to many places, all named after the session id. Trashing moves
every one of those parts into one entry folder under the Trash, in the same folder
shape they came from, next to a manifest that says where each part belongs.
Nothing leaves the disk. Nothing shared between sessions is touched.
"""

from __future__ import annotations

import errno
import fcntl
import fnmatch
import json
import os
import shutil
import stat as statmod
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from conclaude.core.errors import SessionIsLive, SessionNotFound, TrashFailed
from conclaude.core.live import find_live, iter_markers, read_marker
from conclaude.core.model import Part, Session, TrashEntry
from conclaude.core.scan import folder_size
from conclaude.core.settings import Settings

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1

# Inside an entry, the parts sit under this folder, in the shape they had
# under Claude Code's folder. ``ls`` shows exactly where each came from.
CLAUDE_SUBDIR = "claude"

# How many times a name is retried when the same session goes to the Trash
# twice in the same second.
NAME_RETRIES = 100


@contextmanager
def held_lock(settings: Settings) -> Generator[None, None, None]:
    """Hold the Trash lock. Waits until any other holder lets go.

    Two running copies of the tool may both look around freely. Only a move
    takes this lock, so two moves never interleave. The lock is a kernel
    file lock, so it holds across processes and is dropped if one dies.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with open(settings.trash_lock_file, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _matching(folder: Path, pattern: str) -> list[Path]:
    """The entries directly under a folder whose name fits a shell pattern."""
    try:
        entries = os.scandir(folder)
    except OSError:
        return []
    with entries:
        found = [
            Path(entry.path)
            for entry in entries
            if fnmatch.fnmatchcase(entry.name, pattern)
        ]
    found.sort()
    return found


def markers_naming(sessions_dir: Path, session_id: str) -> list[Path]:
    """Every process marker under ``sessions/`` that names this session."""
    found = []
    for _, path in iter_markers(sessions_dir):
        record = read_marker(path)
        if record is not None and record.get("sessionId") == session_id:
            found.append(path)
    return found


def _part(settings: Settings, kind: str, path: Path) -> Part | None:
    """A part for a path, or None when nothing sits there.

    Symlinks are not followed. A link is a part of its own and moves as a
    link, so whatever it points at is never touched.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None
    is_dir = statmod.S_ISDIR(st.st_mode)
    size = folder_size(path) if is_dir else st.st_size
    stored = Path(CLAUDE_SUBDIR) / path.relative_to(settings.claude_dir)
    return Part(kind=kind, original=path, stored=stored, is_dir=is_dir, size=size)


def find_parts(settings: Settings, session: Session) -> list[Part]:
    """Every part of a session that exists on the disk right now.

    Every location is optional. Only what is there is listed. The list is in
    a fixed order: the transcript first, then its sidecar, then the small
    folders, then whatever the shell patterns matched.
    """
    sid = session.id
    transcript = session.transcript_path
    wanted: list[tuple[str, Path]] = [
        ("transcript", transcript),
        ("sidecar", transcript.with_suffix("")),
        ("session-env", settings.session_env_dir / sid),
        ("file-history", settings.file_history_dir / sid),
        ("job", settings.jobs_dir / sid[:8]),
        ("task", settings.tasks_dir / sid),
        ("debug", settings.debug_dir / f"{sid}.txt"),
        ("team", settings.teams_dir / sid),
    ]
    wanted += [("marker", p) for p in markers_naming(settings.sessions_dir, sid)]
    wanted += [("todo", p) for p in _matching(settings.todos_dir, f"*{sid}*")]
    wanted += [
        ("telemetry", p) for p in _matching(settings.telemetry_dir, f"*.{sid}.*")
    ]
    parts = []
    for kind, path in wanted:
        part = _part(settings, kind, path)
        if part is not None:
            parts.append(part)
    return parts


def copy_then_remove(source: Path, target: Path) -> None:
    """Move by copying and then removing the original.

    This is what a move degrades to across two filesystems. Symlinks are
    copied as links, never followed, so nothing outside the source is read
    or removed.
    """
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target, symlinks=True)
        shutil.rmtree(source)
    else:
        shutil.copy2(source, target, follow_symlinks=False)
        os.unlink(source)


def move(source: Path, target: Path) -> None:
    """Move a file or a folder, across filesystems if it must.

    A rename is atomic and is tried first. When the two sides sit on
    different filesystems the kernel refuses, and the part is copied and
    then removed. The result is the same either way.
    """
    try:
        os.rename(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        copy_then_remove(source, target)


def entry_name(settings: Settings, session_id: str, moment: datetime) -> str:
    """The name of an entry folder: when it was made, then the session id."""
    when = moment.astimezone().strftime(settings.trash_name_pattern)
    return f"{when}_{session_id}"


def _make_entry_dir(settings: Settings, session_id: str, moment: datetime) -> Path:
    """A fresh, empty entry folder. Never an existing one."""
    settings.trash_dir.mkdir(parents=True, exist_ok=True)
    base = entry_name(settings, session_id, moment)
    for attempt in range(1, NAME_RETRIES + 1):
        name = base if attempt == 1 else f"{base}-{attempt}"
        path = settings.trash_dir / name
        try:
            os.mkdir(path)
        except FileExistsError:
            continue
        return path
    raise FileExistsError(errno.EEXIST, "too many entries with this name", str(base))


def write_manifest(entry: TrashEntry) -> Path:
    """Write ``manifest.json`` into the entry folder and return its path."""
    record: dict[str, Any] = {"version": MANIFEST_VERSION, **entry.to_dict()}
    path = entry.path / MANIFEST_NAME
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def trash_session(
    settings: Settings,
    session: Session,
    reason: str | None = None,
    now: datetime | None = None,
) -> TrashEntry:
    """Move every part of a session into a new Trash entry and return it.

    A live session is refused. The check is made fresh, under the lock, so
    a session that started running since the list was read is still safe.

    The manifest is written before the first part moves. If the move stops
    half way, the manifest still says where every part belongs.
    """
    with held_lock(settings):
        live = find_live(settings).get(session.id)
        if live is not None:
            raise SessionIsLive(session.id, live.pid)
        parts = find_parts(settings, session)
        if not parts:
            raise SessionNotFound(session.id)
        moment = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        try:
            entry_dir = _make_entry_dir(settings, session.id, moment)
        except OSError as error:
            raise TrashFailed(session.id, settings.trash_dir, error) from error
        entry = TrashEntry(
            id=entry_dir.name,
            path=entry_dir,
            session_id=session.id,
            trashed_at=moment,
            reason=reason,
            title=session.title,
            project_path=session.project_path,
            parts=tuple(parts),
        )
        try:
            write_manifest(entry)
        except OSError as error:
            raise TrashFailed(session.id, entry_dir / MANIFEST_NAME, error) from error
        for part in parts:
            target = entry_dir / part.stored
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                move(part.original, target)
            except OSError as error:
                raise TrashFailed(session.id, part.original, error) from error
        return entry
