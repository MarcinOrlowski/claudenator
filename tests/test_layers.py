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

import ast
import subprocess
import sys
from pathlib import Path

import conclaude.core

FORBIDDEN = {"textual", "rich"}


def _imported_roots(tree: ast.AST) -> list[str]:
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module.split(".")[0])
    return roots


def test_no_core_module_imports_the_terminal_library() -> None:
    """No core module imports the terminal library."""
    core_dir = Path(conclaude.core.__file__).parent
    offenders = []
    for path in sorted(core_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders += [
            f"{path.name} imports {root}"
            for root in _imported_roots(tree)
            if root in FORBIDDEN
        ]

    assert offenders == []


def test_loading_the_store_and_the_command_line_does_not_load_the_terminal_library() -> (
    None
):
    """Loading the store and the command line does not load the terminal library."""
    code = (
        "import sys, conclaude.core.store, conclaude.cli.main; "
        "loaded = {name.split('.')[0] for name in sys.modules}; "
        f"assert not loaded & {FORBIDDEN!r}, loaded & {FORBIDDEN!r}"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
