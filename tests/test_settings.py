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

from pathlib import Path

import pytest

from conclaude.core.settings import Settings


def test_defaults_give_the_three_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults give the three roots."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    settings = Settings()

    assert settings.claude_dir == Path.home() / ".claude"
    assert settings.data_dir == Path.home() / ".local" / "share" / "conclaude"
    assert settings.proc_dir == Path("/proc")


def test_every_location_derives_from_a_root(tmp_path: Path) -> None:
    """Every location derives from a root."""
    settings = Settings(claude_dir=tmp_path / "cc", data_dir=tmp_path / "own")

    assert settings.projects_dir == tmp_path / "cc" / "projects"
    assert settings.sessions_dir == tmp_path / "cc" / "sessions"
    assert settings.history_file == tmp_path / "cc" / "history.jsonl"
    assert settings.session_env_dir == tmp_path / "cc" / "session-env"
    assert settings.file_history_dir == tmp_path / "cc" / "file-history"
    assert settings.jobs_dir == tmp_path / "cc" / "jobs"
    assert settings.tasks_dir == tmp_path / "cc" / "tasks"
    assert settings.debug_dir == tmp_path / "cc" / "debug"
    assert settings.todos_dir == tmp_path / "cc" / "todos"
    assert settings.telemetry_dir == tmp_path / "cc" / "telemetry"
    assert settings.teams_dir == tmp_path / "cc" / "teams"
    assert settings.trash_dir == tmp_path / "own" / "trash"
    assert settings.trash_lock_file == tmp_path / "own" / "trash.lock"
    assert settings.cache_file == tmp_path / "own" / "cache.db"


def test_claude_code_config_dir_is_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Claude code config dir is honoured."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere"))

    assert Settings().claude_dir == tmp_path / "elsewhere"


def test_xdg_data_home_is_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Xdg data home is honoured."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert Settings().data_dir == tmp_path / "xdg" / "conclaude"


def test_screen_defaults_are_present() -> None:
    """Screen defaults are present."""
    settings = Settings()

    assert settings.theme == "textual-dark"
    assert settings.sort_column == "last_used"
    assert settings.sort_descending is True
    assert settings.projects_pane_min_width < settings.projects_pane_max_width
    assert 0 < settings.projects_pane_min_height
    # The window shrinks through both steps in turn: the panes go in one column,
    # and only then a message takes the place of them all.
    assert settings.min_width < settings.stack_panes_below
    assert 0 < settings.min_height
    assert settings.confirm_delete is False
    assert settings.time_format == "relative"
    assert settings.cut_mark
    assert 0 <= settings.cut_head_share <= 1
