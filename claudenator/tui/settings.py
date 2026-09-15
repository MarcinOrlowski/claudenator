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
    """What the user chose or typed, as the option can hold it, or None.

    A box of its own hands back a text, even for a number, so a number is made
    from it here. A text the option cannot hold gives None, and the caller
    leaves the option as it was.
    """
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
    """The box where a number or a free text is typed.

    The library gives 'ctrl+d' to this box, to take out the character on the
    right. The settings screen needs that key for the default of an option, so
    this box hands it back. 'delete' still takes out the character.
    """

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
    """The settings box: every option the user may change, in sections.

    A change takes effect as the user makes it, behind the box. 'ctrl+s'
    writes the file and closes. 'escape' puts every option back to what it
    was when the box opened, and the file is not touched.
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("f2", "next_group", "Next section"),
        Binding("ctrl+d", "reset_one", "Default"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        # What every option held when the box opened. This is what 'escape'
        # puts back, and it is taken before the user can change a thing.
        self.before = values_of(settings)

    def compose(self) -> ComposeResult:
        box = Vertical(id="settings")
        box.border_title = "Settings"
        with box:
            with TabbedContent():
                for group in groups():
                    with TabPane(group, id=slug(group)):
                        # 'tab' moves from one option to the next, and never
                        # stops on the page itself. A long section still
                        # scrolls: the library brings the focused option in.
                        with VerticalScroll(classes="option-page", can_focus=False):
                            for option in options_in(group):
                                yield OptionRow(
                                    option,
                                    getattr(self.settings, option.name),
                                    self._choices(option),
                                )
            with Horizontal(id="settings-buttons"):
                yield Button("Reset all", id="reset-all")
        yield Footer()

    def action_save(self) -> None:
        """The 'ctrl+s' key: the file is written, and the box closes."""
        try:
            path = save_file(self.settings)
        except ClaudenatorError as error:
            self.notify(str(error), title="Not saved", severity="error")
            return
        self.notify(f"Saved to {path}", title="Settings")
        self.dismiss(True)

    def action_cancel(self) -> None:
        """The 'escape' key: every option goes back, and the file is not touched."""
        put_values(self.settings, self.before)
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """The 'Reset all' button: every option goes back to its default."""
        event.stop()
        for row in self.query(OptionRow):
            self._put_default(row)
        self._tell()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """A true or false option was turned over."""
        event.stop()
        self._take(event.switch, event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        """An option with a list of choices took one of them."""
        event.stop()
        self._take(event.select, str(event.value))

    def on_input_changed(self, event: Input.Changed) -> None:
        """A number or a text was typed.

        A value the option cannot hold changes nothing: the box marks itself
        and the option keeps what it had, so a half-typed number is never taken.
        """
        event.stop()
        result = event.validation_result
        if result is not None and not result.is_valid:
            return
        self._take(event.input, event.value)

    def _choices(self, option: Option) -> tuple[str, ...]:
        """What one option may hold. The themes are the app's own list."""
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

    def _tell(self) -> None:
        """Ask the app to put the settings in effect, behind the box.

        The message goes to the app itself, not up from the box, so that it
        still arrives when the box is on its way out.
        """
        self.app.post_message(SettingsChanged())
