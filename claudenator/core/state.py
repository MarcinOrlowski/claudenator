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

import tomllib
from dataclasses import dataclass
from pathlib import Path

from claudenator.core.config import quote

HEADER = (
    "# claudenator: what the last run had highlighted.",
    "# The tool writes this file. See 'remember_selection'.",
    "",
)


@dataclass(frozen=True)
class State:
    """What the last run had highlighted.

    ``project`` is a ``Project.path``, and None for 'All projects'.
    ``session`` is a ``Session.id``.
    """

    project: str | None = None
    session: str | None = None


def _text(value: object) -> str | None:
    """``value`` when it is a text with something in it, None otherwise."""
    return value if isinstance(value, str) and value else None


def read_state(path: Path) -> State:
    """What the file holds. A missing, empty or broken file gives an empty state."""
    try:
        with path.open("rb") as handle:
            table = tomllib.load(handle)
    except (OSError, ValueError):
        return State()
    return State(_text(table.get("last_project")), _text(table.get("last_session")))


def write_state(path: Path, state: State) -> None:
    """Write the file. A write that fails is no reason to hold up the quit."""
    lines: list[str] = list(HEADER)
    if state.project is not None:
        lines.append(f"last_project = {quote(state.project)}")
    if state.session is not None:
        lines.append(f"last_session = {quote(state.session)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([*lines, ""]), encoding="utf-8")
    except OSError:
        pass
