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

from dataclasses import fields
from pathlib import Path

import pytest

from claudenator.core.config import (
    OPTIONS,
    apply_file,
    as_toml,
    check,
    default_of,
    dump,
    groups,
    kind_of,
    options_in,
    put_values,
    save_file,
    values_of,
)
from claudenator.core.errors import SettingsNotSaved
from claudenator.core.settings import Settings, default_config_file


def test_the_file_sits_under_the_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The file sits under the config home."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert default_config_file() == tmp_path / "xdg" / "claudenator" / "config.toml"


def test_the_config_home_falls_back_to_the_home_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config home falls back to the home folder."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert (
        default_config_file() == Path.home() / ".config" / "claudenator" / "config.toml"
    )


def test_every_option_names_a_field_of_the_settings_object() -> None:
    """Every option names a field of the settings object."""
    known = {field.name for field in fields(Settings)}

    assert [option.name for option in OPTIONS if option.name not in known] == []
    # Every one of them holds a flat value, so the file needs no table.
    assert {kind_of(option.name) for option in OPTIONS} <= {bool, int, float, str}


def test_every_option_belongs_to_one_section() -> None:
    """Every option belongs to one section."""
    named = [option for group in groups() for option in options_in(group)]

    assert named == list(OPTIONS)
    assert groups() == ["General", "Lists", "Times", "Trash"]


def test_a_file_that_goes_out_comes_back_the_same(settings: Settings) -> None:
    """A file that goes out comes back the same."""
    settings.theme = "gruvbox"
    settings.confirm_delete = True
    settings.confirm_purge = False
    settings.sort_descending = False
    settings.time_pattern = "%H:%M"
    save_file(settings)

    back = Settings(config_file=settings.config_file)
    notes = apply_file(back)

    assert notes == []
    assert values_of(back) == values_of(settings)


def test_a_missing_file_is_not_a_fault(settings: Settings) -> None:
    """A missing file is not a fault."""
    assert not settings.config_file.exists()

    notes = apply_file(settings)

    assert notes == []
    assert values_of(settings) == values_of(Settings())


def test_a_file_that_cannot_be_read_gives_the_defaults_and_one_note(
    settings: Settings,
) -> None:
    """A file that cannot be read gives the defaults and one note."""
    settings.config_file.parent.mkdir(parents=True)
    settings.config_file.write_text("this is not = = toml\n", encoding="utf-8")

    notes = apply_file(settings)

    assert len(notes) == 1
    assert str(settings.config_file) in notes[0]
    assert values_of(settings) == values_of(Settings())


def test_one_bad_value_never_drops_the_rest_of_the_file(settings: Settings) -> None:
    """One bad value never drops the rest of the file."""
    settings.config_file.parent.mkdir(parents=True)
    settings.config_file.write_text(
        'theme = "gruvbox"\nconfirm_delete = "yes"\nstart_pane = "projects"\n',
        encoding="utf-8",
    )

    notes = apply_file(settings)

    assert len(notes) == 1
    assert "confirm_delete" in notes[0]
    assert settings.theme == "gruvbox"
    assert settings.start_pane == "projects"
    assert settings.confirm_delete is default_of("confirm_delete")


def test_a_name_that_is_not_an_option_is_left_out(settings: Settings) -> None:
    """A name that is not an option is left out."""
    settings.config_file.parent.mkdir(parents=True)
    settings.config_file.write_text(
        'claude_dir = "/somewhere/else"\ntheme = "nord"\n', encoding="utf-8"
    )

    notes = apply_file(settings)

    assert len(notes) == 1
    assert "claude_dir" in notes[0]
    assert settings.claude_dir != Path("/somewhere/else")
    assert settings.theme == "nord"


def test_the_file_holds_every_option(settings: Settings) -> None:
    """The file holds every option.

    A value at its default is written too. That locks it: a later release may
    change a default, and the file keeps the one the user saved.
    """
    settings.theme = "nord"

    text = dump(settings)
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]

    assert lines[0] == 'theme = "nord"'
    assert "sort_descending = true" in lines
    assert [line.split(" = ")[0] for line in lines] == [
        option.name for option in OPTIONS
    ]


def test_the_file_names_the_section_of_every_option(settings: Settings) -> None:
    """The file names the section of every option, as the settings screen does."""
    wanted = [f"# {group}" for group in groups()]

    marks = [line for line in dump(settings).splitlines() if line in wanted]

    assert marks == wanted


def test_an_option_back_at_its_default_stays_in_the_file(settings: Settings) -> None:
    """An option back at its default stays in the file."""
    settings.theme = "nord"
    save_file(settings)
    with_theme = settings.config_file.read_text(encoding="utf-8")

    settings.theme = default_of("theme")
    save_file(settings)
    back = settings.config_file.read_text(encoding="utf-8")

    assert 'theme = "nord"' in with_theme
    assert f"theme = {as_toml(default_of('theme'))}" in back


def test_a_text_with_a_quote_in_it_comes_back_whole(settings: Settings) -> None:
    """A text with a quote in it comes back whole."""
    settings.time_pattern = 'a "b" \\ c'
    save_file(settings)

    back = Settings(config_file=settings.config_file)
    notes = apply_file(back)

    assert notes == []
    assert back.time_pattern == 'a "b" \\ c'


def test_a_value_of_another_kind_keeps_the_default() -> None:
    """A value of another kind keeps the default."""
    assert check("confirm_delete", 1) is None
    assert check("confirm_purge", "yes") is None
    assert check("time_pattern", 7) is None
    assert check("sort_descending", "true") is None
    assert check("confirm_purge", False) is False


def test_a_text_that_is_not_one_of_the_choices_keeps_the_default() -> None:
    """A text that is not one of the choices keeps the default."""
    assert check("start_pane", "trash") is None
    assert check("list_time_format", "both") == "both"
    assert check("sort_column", "size") == "size"
    # The app holds the list of themes, so any text goes in here.
    assert check("theme", "a-theme-of-my-own") == "a-theme-of-my-own"


def test_a_file_that_cannot_be_written_says_so(settings: Settings) -> None:
    """A file that cannot be written says so."""
    blocked = settings.config_file.parent
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("I am a file, not a folder\n", encoding="utf-8")

    with pytest.raises(SettingsNotSaved) as raised:
        save_file(settings)

    assert str(settings.config_file) in str(raised.value)


def test_the_values_of_the_options_go_out_and_come_back(settings: Settings) -> None:
    """The values of the options go out and come back."""
    before = values_of(settings)
    settings.theme = "nord"
    settings.confirm_delete = True

    put_values(settings, before)

    assert values_of(settings) == before
    assert settings.claude_dir == settings.claude_dir
