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
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from claudenator.core.errors import SettingsNotSaved
from claudenator.core.format import TIME_FORMATS
from claudenator.core.settings import Settings

# What one option may hold
Value = bool | int | float | str

# The kind of value a field holds
KINDS: dict[str, type] = {"bool": bool, "int": int, "float": float, "str": str}

# The sections of the settings screen
GENERAL = "General"
LISTS = "Lists"
TIMES = "Times"
TRASH = "Trash"

THEME = "theme"

# The columns the sessions table can sort by
SORT_COLUMNS = ("state", "title", "last_used", "size", "msgs", "project")

# Which pane holds the focus at start.
START_PANES = ("sessions", "projects")


@dataclass(frozen=True)
class Option:
    """One choice the user may change"""

    name: str
    group: str
    label: str
    note: str
    choices: tuple[str, ...] = ()
    low: float | None = None
    high: float | None = None


OPTIONS: tuple[Option, ...] = (
    Option(
        THEME,
        GENERAL,
        "Theme",
        "The colours of every part of the screen.",
    ),
    Option(
        "start_pane",
        GENERAL,
        "Start pane",
        "The pane that holds the focus at start.",
        choices=START_PANES,
    ),
    Option(
        "sort_column",
        LISTS,
        "Sort column",
        "The column that orders the sessions at start.",
        choices=SORT_COLUMNS,
    ),
    Option(
        "sort_descending",
        LISTS,
        "Sort descending",
        "Biggest and newest first.",
    ),
    Option(
        "list_time_format",
        TIMES,
        "List time",
        "How a time reads in a column.",
        choices=TIME_FORMATS,
    ),
    Option(
        "details_time_format",
        TIMES,
        "Details time",
        "How a time reads in the details.",
        choices=TIME_FORMATS,
    ),
    Option(
        "time_pattern",
        TIMES,
        "Time pattern",
        "The form of an exact time, as strftime writes it.",
    ),
    Option(
        "confirm_delete",
        TRASH,
        "Confirm delete",
        "Ask before a session goes to the Trash.",
    ),
    Option(
        "confirm_purge",
        TRASH,
        "Confirm purge",
        "Ask before a Trash entry leaves the disk for good.",
    ),
)

BY_NAME: dict[str, Option] = {option.name: option for option in OPTIONS}

_KINDS_BY_FIELD: dict[str, type] = {
    field.name: KINDS[field.type]
    for field in fields(Settings)
    if isinstance(field.type, str) and field.type in KINDS
}

HEADER = (
    "# claudenator settings",
    "#",
    "# Copyright ©2026 Marcin Orlowski <MarcinOrlowski.com>",
    "# https://github.com/MarcinOrlowski/claudenator",
    "#",
    "",
)


def groups() -> list[str]:
    """Config groups"""
    found: list[str] = []
    for option in OPTIONS:
        if option.group not in found:
            found.append(option.group)
    return found


def options_in(group: str) -> list[Option]:
    """Group options"""
    return [option for option in OPTIONS if option.group == group]


def kind_of(name: str) -> type:
    """The kind of value one option holds"""
    return _KINDS_BY_FIELD[name]


def default_of(name: str) -> Value:
    """Returns default value of given option"""
    return getattr(Settings(), name)


def values_of(settings: Settings) -> dict[str, Value]:
    """What every option value is"""
    return {option.name: getattr(settings, option.name) for option in OPTIONS}


def put_values(settings: Settings, values: Mapping[str, Value]) -> None:
    """Put these values into ``settings``"""
    for name, value in values.items():
        setattr(settings, name, value)


def check(name: str, value: object) -> Value | None:
    """``value`` as the option can hold it, or None.

    A whole number is taken for a fraction, because TOML writes ``1`` for ``1.0``.
    """
    option = BY_NAME.get(name)
    if option is None:
        return None
    kind = kind_of(name)
    if kind is bool:
        return value if isinstance(value, bool) else None
    # True is a whole number in Python. It is not one here.
    if isinstance(value, bool):
        return None
    if kind is str:
        if not isinstance(value, str):
            return None
        if option.choices and value not in option.choices:
            return None
        return value
    if kind is int:
        if not isinstance(value, int):
            return None
        number: int | float = value
    else:
        if not isinstance(value, (int, float)):
            return None
        number = float(value)
    if option.low is not None and number < option.low:
        return None
    if option.high is not None and number > option.high:
        return None
    return number


def read_file(path: Path) -> tuple[dict[str, object], list[str]]:
    """Tries to read config"""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle), []
    except FileNotFoundError:
        return {}, []
    except (OSError, tomllib.TOMLDecodeError) as cause:
        return {}, [f"{path} could not be read ({cause}). The defaults are in effect."]


def apply_file(settings: Settings) -> list[str]:
    """Put settings file contente into ``settings``"""
    table, notes = read_file(settings.config_file)
    for name, value in table.items():
        if name not in BY_NAME:
            notes.append(f"'{name}' is not an option. It was left out.")
            continue
        taken = check(name, value)
        if taken is None:
            notes.append(f"'{name}' cannot hold {value!r}. Its default is in effect.")
            continue
        setattr(settings, name, taken)
    return notes


def quote(text: str) -> str:
    """``text`` as TOML writes a string."""
    out = ['"']
    for char in text:
        if char in '"\\':
            out.append("\\" + char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif char < " " or char == "\x7f":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def as_toml(value: Value) -> str:
    """One value as TOML writes it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return quote(value)
    return repr(value)


def dump(settings: Settings) -> str:
    """Every option as it stands now, in sections, as the settings screen lists them.

    A value at its default goes in the file like any other. That is what locks
    it: a later release may change a default, and the file holds the user's.
    """
    lines: list[str] = list(HEADER)
    for group in groups():
        lines.append(f"# {group}")
        lines += [
            f"{option.name} = {as_toml(getattr(settings, option.name))}"
            for option in options_in(group)
        ]
        lines.append("")
    return "\n".join(lines)


def save_file(settings: Settings) -> Path:
    """Write the settings file. Returns the file written.

    The folder is made when it is not there. Nothing but this writes the file.
    """
    path = settings.config_file
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(settings), encoding="utf-8")
    except OSError as cause:
        raise SettingsNotSaved(path, cause) from cause
    return path
