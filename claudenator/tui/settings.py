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

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.validation import Integer, Number
from textual.widget import Widget
from textual.widgets import (
    Button,
    Footer,
    Input,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from claudenator.core.config import (
    THEME,
    Option,
    Value,
    check,
    default_of,
    groups,
    kind_of,
    options_in,
    put_values,
    save_file,
    values_of,
)
from claudenator.core.errors import ClaudenatorError
from claudenator.core.settings import Settings


def slug(group: str) -> str:
    """The id of the tab that holds one section."""
    return group.lower().replace(" ", "-")


def as_value(option: Option, raw: Value) -> Value | None:
    """What the user chose or typed"""

    kind = kind_of(option.name)
    if kind is not str and isinstance(raw, str):
        try:
            raw = int(raw) if kind is int else float(raw)
        except ValueError:
            return None
    return check(option.name, raw)


class SettingsChanged(Message):
    """One option holds another value now. The app puts it in effect everywhere."""


class OptionInput(Input):
    """Input for free text or numbers"""

    BINDINGS = [Binding("ctrl+d", "screen.reset_one", "Default", show=False)]


class OptionRow(Horizontal):
    """One option: its name at the left, the way to change it at the right."""

    def __init__(self, option: Option, value: Value, choices: tuple[str, ...]) -> None:
        super().__init__(classes="option-row")
        self.option = option
        self.value = value
        self.choices = choices

    def compose(self) -> ComposeResult:
        yield Static(self.option.label, classes="option-label", markup=False)
        yield self._editor()

    @property
    def editor(self) -> Widget:
        """The widget that changes this option."""
        return self.query_one(".option-value")

    def put(self, value: Value) -> None:
        """Show ``value`` in the editor, as the user would have set it."""
        editor = self.editor
        if isinstance(editor, Switch):
            editor.value = bool(value)
        elif isinstance(editor, Select):
            editor.value = str(value)
        elif isinstance(editor, Input):
            editor.value = str(value)

    def _editor(self) -> Widget:
        """The widget this option is changed with: a switch, a list, or a box."""
        option = self.option
        kind = kind_of(option.name)
        if kind is bool:
            return Switch(
                value=bool(self.value),
                tooltip=option.note,
                classes="option-value",
            )
        if self.choices:
            return Select(
                [(choice, choice) for choice in self.choices],
                value=str(self.value),
                allow_blank=False,
                tooltip=option.note,
                classes="option-value",
            )
        return OptionInput(
            value=str(self.value),
            type="integer" if kind is int else "number" if kind is float else "text",
            validators=self._bounds(),
            tooltip=option.note,
            classes="option-value",
        )

    def _bounds(self) -> list[Integer | Number]:
        """What the box accepts: the bounds of a number, or nothing for a text."""
        kind = kind_of(self.option.name)
        if kind is int:
            return [Integer(minimum=self.option.low, maximum=self.option.high)]
        if kind is float:
            return [Number(minimum=self.option.low, maximum=self.option.high)]
        return []


class SettingsScreen(ModalScreen[bool]):
    """The settings box"""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+a", "apply", "Apply"),
        Binding("f2", "next_group", "Next section"),
        Binding("ctrl+d", "reset_one", "Default"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        # The last applied state, which Cancel puts back. Apply moves it on.
        self.applied = values_of(settings)

    def compose(self) -> ComposeResult:
        box = Vertical(id="settings")
        box.border_title = "Settings"
        with box:
            with TabbedContent():
                for group in groups():
                    with TabPane(group, id=slug(group)):
                        # Not focusable: 'tab' goes from option to option. A long
                        # section still scrolls, on the option that takes focus.
                        with VerticalScroll(classes="option-page", can_focus=False):
                            for option in options_in(group):
                                yield OptionRow(
                                    option,
                                    getattr(self.settings, option.name),
                                    self._choices(option),
                                )
            with Horizontal(id="settings-buttons"):
                yield Button("Reset all", id="reset-all")
                yield Static(classes="button-gap")
                yield Button("Save", id="save", variant="primary")
                yield Button("Apply", id="apply")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def action_save(self) -> None:
        """Save: the file is written, and the box closes."""
        if self._write():
            self.dismiss(True)

    def action_apply(self) -> None:
        """Apply: the file is written, and the box stays open."""
        if self._write():
            self.applied = values_of(self.settings)

    def action_cancel(self) -> None:
        """Cancel: every option goes back to the last applied state, and closes."""
        put_values(self.settings, self.applied)
        self._tell()
        self.dismiss(False)

    def action_reset_one(self) -> None:
        """The 'ctrl+d' key: the option under the cursor goes back to its default."""
        row = self._row_of(self.focused) if self.focused is not None else None
        if row is None:
            return
        self._put_default(row)
        self._tell()

    def action_next_group(self) -> None:
        """The 'F2' key: the next section comes to the front, the last one wraps."""
        tabs = self.query_one(TabbedContent)
        names = [slug(group) for group in groups()]
        here = names.index(tabs.active) if tabs.active in names else -1
        tabs.active = names[(here + 1) % len(names)]

    def action_reset_all(self) -> None:
        """Reset every option goes back to its default."""

        for row in self.query(OptionRow):
            self._put_default(row)
        self._tell()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """A button at the foot of the box."""
        event.stop()
        pressed = {
            "save": self.action_save,
            "apply": self.action_apply,
            "cancel": self.action_cancel,
            "reset-all": self.action_reset_all,
        }.get(str(event.button.id))
        if pressed is not None:
            pressed()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """A true or false option was turned over."""
        event.stop()
        self._take(event.switch, event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        """An option with a list of choices took one of them."""
        event.stop()
        self._take(event.select, str(event.value))

    def on_input_changed(self, event: Input.Changed) -> None:
        """A number or a text was typed."""
        event.stop()
        result = event.validation_result
        if result is not None and not result.is_valid:
            return
        self._take(event.input, event.value)

    def _choices(self, option: Option) -> tuple[str, ...]:
        """What one option may hold."""
        if option.name == THEME:
            return tuple(self.app.available_themes)
        return option.choices

    def _row_of(self, widget: Widget) -> OptionRow | None:
        """The row one widget sits in, or None when the focus is somewhere else."""
        for node in widget.ancestors_with_self:
            if isinstance(node, OptionRow):
                return node
        return None

    def _put_default(self, row: OptionRow) -> None:
        """One option back to its default, in the settings and in its editor."""
        value = default_of(row.option.name)
        setattr(self.settings, row.option.name, value)
        row.put(value)

    def _take(self, editor: Widget, raw: Value) -> None:
        """Put what one editor holds into the settings object."""
        row = self._row_of(editor)
        if row is None:
            return
        value = as_value(row.option, raw)
        if value is None:
            return
        setattr(self.settings, row.option.name, value)
        self._tell()

    def _write(self) -> bool:
        """Write the settings file. False when it could not be written."""
        try:
            path = save_file(self.settings)
        except ClaudenatorError as error:
            self.notify(str(error), title="Not saved", severity="error")
            return False
        self.notify(f"Saved to {path}", title="Settings")
        return True

    def _tell(self) -> None:
        """Ask the app to put the settings in effect, behind the box.

        Straight to the app, so it still arrives when the box is on its way out.
        """
        self.app.post_message(SettingsChanged())
