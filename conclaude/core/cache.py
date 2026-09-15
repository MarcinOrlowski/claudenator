"""
##################################################################################
#
# conClaude by Marcin Orlowski
# The only Claude Code session manager you need.
#
# @author    Marcin Orlowski <mail@marcinOrlowski.com>
# Copyright  ©2026 Marcin Orlowski <MarcinOrlowski.com>
# @link      https://github.com/MarcinOrlowski/conclaude
#
##################################################################################
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from conclaude.core.errors import CacheDamaged
from conclaude.core.model import Figures
from conclaude.core.settings import Settings

# One row per transcript, found by its path. The size and change time say
# which copy of the file the row describes. The row holds our own numbers
# and nothing the user wrote. A time is stored whole, so what comes back
# is what went in.
SCHEMA = """
CREATE TABLE IF NOT EXISTS figures (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    scanned_at TEXT NOT NULL,
    turns INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    models TEXT NOT NULL,
    tools TEXT NOT NULL,
    first_at TEXT,
    last_at TEXT
)
"""
COLUMNS = (
    "path",
    "size",
    "mtime_ns",
    "scanned_at",
    "turns",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "models",
    "tools",
    "first_at",
    "last_at",
)
# How long a write waits for another copy of the tool to finish its own.
LOCK_WAIT_SECONDS = 5.0


def _moment(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _pairs(value: Any) -> tuple[tuple[str, int], ...]:
    """The name and count pairs stored as one JSON list, in their stored order."""
    return tuple((str(name), int(count)) for name, count in json.loads(value))


def _row_of(figures: Figures) -> tuple[Any, ...]:
    return (
        str(figures.transcript_path),
        figures.transcript_size,
        figures.transcript_mtime_ns,
        figures.scanned_at.isoformat(),
        figures.turns,
        figures.input_tokens,
        figures.output_tokens,
        figures.cache_read_tokens,
        figures.cache_write_tokens,
        json.dumps(figures.models),
        json.dumps(figures.tools),
        figures.first_at.isoformat() if figures.first_at else None,
        figures.last_at.isoformat() if figures.last_at else None,
    )


def _is_stale(transcript: Path, row: tuple[Any, ...]) -> bool:
    """True when the file's size or change time differ from the row's, or it is gone."""
    try:
        stat = transcript.stat()
    except OSError:
        return True
    return stat.st_size != row[1] or stat.st_mtime_ns != row[2]


def _figures_of(row: tuple[Any, ...], stale: bool) -> Figures:
    return Figures(
        transcript_path=Path(row[0]),
        transcript_size=row[1],
        transcript_mtime_ns=row[2],
        scanned_at=datetime.fromisoformat(row[3]),
        turns=row[4],
        input_tokens=row[5],
        output_tokens=row[6],
        cache_read_tokens=row[7],
        cache_write_tokens=row[8],
        models=_pairs(row[9]),
        tools=_pairs(row[10]),
        first_at=_moment(row[11]),
        last_at=_moment(row[12]),
        stale=stale,
    )


class Cache:
    """The numbers a deep scan found, kept in one SQLite file in the tool's own folder.

    A row is found by the transcript's path. A transcript that changed since
    its scan still gives its row back, marked stale, so the old numbers stay
    on view until a new scan replaces them.
    """

    def __init__(self, settings: Settings) -> None:
        self.path = settings.cache_file

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=LOCK_WAIT_SECONDS)
        try:
            connection.execute(SCHEMA)
        except sqlite3.DatabaseError as error:
            connection.close()
            raise CacheDamaged(self.path, error) from error
        return connection

    def get(self, transcript: Path) -> Figures | None:
        """The figures of one transcript, or None when it was never scanned.

        The figures are stale when the file's size or change time differ from
        the ones the scan saw, or when the file is gone. A damaged cache reads
        as an empty one, so a list or a details pane still works. The next
        ``put`` names the damage.
        """
        if not self.path.exists():
            return None
        names = ", ".join(COLUMNS)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    f"SELECT {names} FROM figures WHERE path = ?", (str(transcript),)
                ).fetchone()
        except CacheDamaged:
            return None
        return _figures_of(row, _is_stale(transcript, row)) if row else None

    def get_all(self) -> dict[Path, Figures]:
        """The figures of every transcript ever scanned, by path, in one read.

        Each is marked stale the same way ``get`` marks it. A missing or a
        damaged cache gives an empty dict.
        """
        if not self.path.exists():
            return {}
        names = ", ".join(COLUMNS)
        try:
            with self._connect() as connection:
                rows = connection.execute(f"SELECT {names} FROM figures").fetchall()
        except CacheDamaged:
            return {}
        return {
            Path(row[0]): _figures_of(row, _is_stale(Path(row[0]), row)) for row in rows
        }

    def put(self, figures: Figures) -> None:
        """Remember the figures of one transcript, in place of any older ones."""
        marks = ", ".join("?" for _ in COLUMNS)
        names = ", ".join(COLUMNS)
        with self._connect() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO figures ({names}) VALUES ({marks})",
                _row_of(figures),
            )

    def forget_missing(self) -> int:
        """Drop the rows of transcripts that are no longer on the disk. Returns how many."""
        if not self.path.exists():
            return 0
        with self._connect() as connection:
            paths = [row[0] for row in connection.execute("SELECT path FROM figures")]
            gone = [(path,) for path in paths if not Path(path).exists()]
            connection.executemany("DELETE FROM figures WHERE path = ?", gone)
        return len(gone)
