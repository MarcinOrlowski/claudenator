"""Shared fixtures: a fake Claude Code folder and settings that point at it."""

from __future__ import annotations

from pathlib import Path

import pytest

from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore
from tests.fabricate import FakeClaude, make_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings whose three roots all sit inside the temporary directory."""
    return make_settings(tmp_path)


@pytest.fixture
def fake(settings: Settings) -> FakeClaude:
    """An empty Claude Code folder at ``settings.claude_dir``."""
    return FakeClaude(settings.claude_dir)


@pytest.fixture
def store(settings: Settings, fake: FakeClaude) -> SessionStore:
    """A store that reads the fake folder."""
    return SessionStore(settings)
