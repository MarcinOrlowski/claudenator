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

import asyncio
import inspect
from pathlib import Path

import pytest

from claudenator.core.settings import Settings
from claudenator.core.store import SessionStore
from tests.fabricate import FakeClaude, FakeProc, make_settings


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Run an ``async def`` test to its end on a fresh event loop.

    The screen tests drive Textual through its pilot, which is async. This
    keeps them plain coroutines and asks for no extra plugin.
    """
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    wanted = inspect.signature(pyfuncitem.obj).parameters
    asyncio.run(pyfuncitem.obj(**{name: pyfuncitem.funcargs[name] for name in wanted}))
    return True


@pytest.fixture(autouse=True)
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the settings file at the temporary directory, for tests"""

    home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    return home


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings whose three roots all sit inside the temporary directory."""
    return make_settings(tmp_path)


@pytest.fixture
def fake(settings: Settings) -> FakeClaude:
    """An empty Claude Code folder at ``settings.claude_dir``."""
    return FakeClaude(settings.claude_dir)


@pytest.fixture
def proc(settings: Settings) -> FakeProc:
    """An empty process table at ``settings.proc_dir``."""
    return FakeProc(settings.proc_dir)


@pytest.fixture
def store(settings: Settings, fake: FakeClaude) -> SessionStore:
    """A store that reads the fake folder."""
    return SessionStore(settings)
