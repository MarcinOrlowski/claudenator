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
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Static


class ConfirmScreen(ModalScreen[bool]):
    """A question with two answers"""

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "No", show=False),
    ]

    def __init__(self, title: str, question: str, subject: str) -> None:
        super().__init__()
        self.box_title = title
        self.question = question
        self.subject = subject

    def compose(self) -> ComposeResult:
        box = Vertical(id="confirm")
        box.border_title = self.box_title
        with box:
            yield Static(self.question, id="confirm-question", markup=False)
            yield Static(self.subject, id="confirm-subject", markup=False)
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", id="yes")
                yield Button("No", id="no", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        """No holds the focus, so 'enter' on its own never removes a thing."""
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Yes or No."""
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        """The 'y' key."""
        self.dismiss(True)

    def action_no(self) -> None:
        """The 'n' key, and 'escape'."""
        self.dismiss(False)
