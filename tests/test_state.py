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

from pathlib import Path

from claudenator.core.settings import Settings
from claudenator.core.state import State, read_state, write_state


def test_remember_selection_starts_on() -> None:
    """The option starts on, so the tool remembers until the user says not to."""
    assert Settings().remember_selection is True


def test_the_state_file_sits_beside_the_cache(tmp_path: Path) -> None:
    """The state file sits in the data folder, beside the cache."""
    settings = Settings(data_dir=tmp_path / "data")

    assert settings.state_file == tmp_path / "data" / "state.toml"


def test_what_goes_in_comes_back_out(tmp_path: Path) -> None:
    """A project and a session go in, and the same two come back."""
    path = tmp_path / "state.toml"
    write_state(path, State("/p/a", "abc-123"))

    assert read_state(path) == State("/p/a", "abc-123")


def test_the_write_makes_the_folder(tmp_path: Path) -> None:
    """A folder that is not there yet is made, as the Trash makes its own."""
    path = tmp_path / "data" / "state.toml"
    write_state(path, State("/p/a", "abc-123"))

    assert path.is_file()


def test_all_projects_leaves_the_project_out(tmp_path: Path) -> None:
    """The 'All projects' line is no project, so the file names none."""
    path = tmp_path / "state.toml"
    write_state(path, State(None, "abc-123"))

    assert "last_project" not in path.read_text(encoding="utf-8")
    assert read_state(path) == State(None, "abc-123")


def test_a_path_with_a_quote_in_it_comes_back_whole(tmp_path: Path) -> None:
    """A path that holds what TOML marks with is written so it reads back the same."""
    odd = '/p/a "b"\\c'
    path = tmp_path / "state.toml"
    write_state(path, State(odd, None))

    assert read_state(path) == State(odd, None)


def test_a_missing_file_gives_an_empty_state(tmp_path: Path) -> None:
    """A file that is not there gives no state and no traceback."""
    assert read_state(tmp_path / "gone.toml") == State()


def test_an_empty_file_gives_an_empty_state(tmp_path: Path) -> None:
    """A file with nothing in it gives no state and no traceback."""
    path = tmp_path / "state.toml"
    path.write_text("", encoding="utf-8")

    assert read_state(path) == State()


def test_a_broken_file_gives_an_empty_state(tmp_path: Path) -> None:
    """A file that is not TOML at all gives no state and no traceback."""
    path = tmp_path / "state.toml"
    path.write_bytes(b"not = = toml\n\xff\xfe")

    assert read_state(path) == State()


def test_a_value_of_the_wrong_kind_is_left_out(tmp_path: Path) -> None:
    """A name that holds a number, or an empty text, counts as none."""
    path = tmp_path / "state.toml"
    path.write_text('last_project = 7\nlast_session = ""\n', encoding="utf-8")

    assert read_state(path) == State()


def test_a_write_that_fails_is_no_traceback(tmp_path: Path) -> None:
    """A folder that cannot be made holds up nothing."""
    blocked = tmp_path / "file"
    blocked.write_text("in the way", encoding="utf-8")

    write_state(blocked / "state.toml", State("/p/a", "abc-123"))
