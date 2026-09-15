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

from claudenator.core.errors import (
    PurgeFailed,
    RestoreClash,
    RestoreFailed,
    SessionIsLive,
    SessionNotFound,
    TrashEntryDamaged,
    TrashEntryNotFound,
    TrashFailed,
)
from claudenator.core.live import find_live, iter_markers, read_marker
from claudenator.core.model import Part, Session, TrashEntry
from claudenator.core.scan import folder_size
from claudenator.core.settings import Settings

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1

# Inside an entry, the parts sit under this folder.
CLAUDE_SUBDIR = "claude"

# How many times a name is retried when the same session goes to the Trash
# twice in the same second.
NAME_RETRIES = 100


@contextmanager
def held_lock(settings: Settings) -> Generator[None, None, None]:
    """Hold the lock to avoid concurrent Trash access by multiple instances."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with open(settings.trash_lock_file, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _matching(folder: Path, pattern: str) -> list[Path]:
    """The entries directly in a folder"""
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

    Symlinks are not resolved and moved as-is. Whatever it points to is not touched.
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
    """Every part of a session that exists on the disk right now."""
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
    """Move by copying and then removing the original."""
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target, symlinks=True)
        shutil.rmtree(source)
    else:
        shutil.copy2(source, target, follow_symlinks=False)
        os.unlink(source)


def move(source: Path, target: Path) -> None:
    """Move a file or a folder. Supports cross filesystems operation."""
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
    """Move session into Trash entry and return it."""
    with held_lock(settings):
        live = find_live(settings).get(session.id)
        if live is not None:
            raise SessionIsLive(session.id, live.pid)
        parts = find_parts(settings, session)
        if not parts:
            raise SessionNotFound(session.id)
        moment = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        if moment.tzinfo is None:
            moment = moment.astimezone()
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


def read_entry(entry_dir: Path) -> TrashEntry | None:
    """The entry in a folder under the Trash, or None it is trash folder one."""
    try:
        with open(entry_dir / MANIFEST_NAME, "rb") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("version") != MANIFEST_VERSION:
        return None
    try:
        return TrashEntry.from_dict(record, entry_dir)
    except ValueError:
        return None


def list_entries(settings: Settings) -> list[TrashEntry]:
    """Every entry in the Trash, newest first."""
    try:
        found = os.scandir(settings.trash_dir)
    except OSError:
        return []
    entries = []
    with found:
        for item in found:
            if not item.is_dir(follow_symlinks=False):
                continue
            entry = read_entry(Path(item.path))
            if entry is not None:
                entries.append(entry)
    entries.sort(key=lambda entry: (entry.trashed_at, entry.id), reverse=True)
    return entries


def total_size(settings: Settings) -> int:
    """Bytes the Trash holds, over every entry."""
    return sum(entry.size for entry in list_entries(settings))


def _entry_dir(settings: Settings, entry: TrashEntry) -> Path:
    """The folder of an entry, from its id. An id is one folder name, never a path."""
    if not entry.id or entry.id in (".", "..") or "/" in entry.id:
        raise TrashEntryNotFound(entry.id)
    return settings.trash_dir / entry.id


def _climbs(path: Path) -> bool:
    """True when a path climbs with ``..``, so it may point outside where it seems to."""
    return ".." in path.parts


def _check_part(settings: Settings, entry: TrashEntry, part: Part) -> tuple[Path, Path]:
    """Checks where a part sits in the entry and where it goes back to."""

    # A manifest is a plain file and may have been edited, so its paths are not trusted.
    stored = entry.path / part.stored
    if (
        part.stored.is_absolute()
        or _climbs(part.stored)
        or part.stored.parts[:1] != (CLAUDE_SUBDIR,)
    ):
        raise TrashEntryDamaged(entry.id, stored, "a part is stored outside the entry")
    target = part.original
    if (
        not target.is_absolute()
        or _climbs(target)
        or not target.is_relative_to(settings.claude_dir)
        or target == settings.claude_dir
    ):
        raise TrashEntryDamaged(
            entry.id, target, "a part belongs outside Claude Code's folder"
        )
    if not os.path.lexists(stored):
        raise TrashEntryDamaged(entry.id, stored, "a part is missing from the entry")
    return stored, target


def restore_entry(settings: Settings, entry: TrashEntry) -> TrashEntry:
    """Put parts of an entry back and drop the Trash entry."""
    with held_lock(settings):
        current = read_entry(_entry_dir(settings, entry))
        if current is None:
            raise TrashEntryNotFound(entry.id)
        moves: list[tuple[Path, Path]] = []
        for part in current.parts:
            stored, target = _check_part(settings, current, part)
            if any(target == other for _, other in moves):
                raise TrashEntryDamaged(current.id, target, "two parts share one place")
            if os.path.lexists(target):
                raise RestoreClash(current.id, target)
            moves.append((stored, target))
        for _stored, target in moves:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise RestoreFailed(current.id, target.parent, error) from error
        for stored, target in moves:
            try:
                move(stored, target)
            except OSError as error:
                raise RestoreFailed(current.id, target, error) from error
        try:
            shutil.rmtree(current.path)
        except OSError as error:
            raise RestoreFailed(current.id, current.path, error) from error
        return current


def purge_entry(settings: Settings, entry: TrashEntry) -> TrashEntry:
    """Remove one entry from the disk for good."""
    with held_lock(settings):
        current = read_entry(_entry_dir(settings, entry))
        if current is None:
            raise TrashEntryNotFound(entry.id)
        try:
            shutil.rmtree(current.path)
        except OSError as error:
            where = current.path
            if error.filename and os.path.isabs(error.filename):
                where = Path(error.filename)
            raise PurgeFailed(current.id, where, error) from error
        return current
