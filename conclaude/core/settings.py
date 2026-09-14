"""The one place that holds every default.

Nothing else in the code carries its own default value or hard-codes a path.
Every other part asks the settings object. Version 1 never reads or writes a
settings file: the object is built with its defaults at start-up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def default_claude_dir() -> Path:
    """Where Claude Code keeps its data.

    Claude Code itself honours ``CLAUDE_CONFIG_DIR``, so we look in the same
    place it writes to.
    """
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


def default_data_dir() -> Path:
    """Where conclaude keeps its own data: the Trash and the cache."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "conclaude"


@dataclass
class Settings:
    """Every choice the tool makes, with its default."""

    # The three roots. Every file location in the core layer derives from these.
    claude_dir: Path = field(default_factory=default_claude_dir)
    data_dir: Path = field(default_factory=default_data_dir)
    proc_dir: Path = Path("/proc")

    # The screen.
    theme: str = "textual-dark"
    sort_column: str = "last_used"
    sort_descending: bool = True
    projects_pane_share: float = 0.25
    projects_pane_min_width: int = 24
    projects_pane_max_width: int = 60
    hide_details_below: int = 100
    hide_projects_below: int = 60
    min_width: int = 30
    min_height: int = 8
    confirm_delete: bool = False

    # How text is shown to a human. See ``format.Formatter``.
    time_format: str = "both"
    time_pattern: str = "%Y-%m-%d %H:%M:%S"

    # Reading transcripts. See ``scan.read_cheap`` for what these bound.
    head_records: int = 500
    tail_bytes: int = 64 * 1024
    tail_bytes_max: int = 4 * 1024 * 1024
    title_max_length: int = 100

    @property
    def projects_dir(self) -> Path:
        """Where the transcripts and their sidecars live."""
        return self.claude_dir / "projects"

    @property
    def sessions_dir(self) -> Path:
        """Where the process markers live."""
        return self.claude_dir / "sessions"

    @property
    def history_file(self) -> Path:
        """Claude Code's prompt history. Read as a fallback, never written."""
        return self.claude_dir / "history.jsonl"

    @property
    def trash_dir(self) -> Path:
        """Where trashed sessions go."""
        return self.data_dir / "trash"

    @property
    def cache_file(self) -> Path:
        """The SQLite cache of costly numbers."""
        return self.data_dir / "cache.db"
