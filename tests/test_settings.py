"""The settings object: one place, every default, three roots."""

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
    assert settings.trash_dir == tmp_path / "own" / "trash"
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
    assert settings.hide_projects_below < settings.hide_details_below
    assert settings.confirm_delete is False
    assert settings.time_format == "both"
