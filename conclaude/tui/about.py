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

from typing import Final

from qrcat import render_qr
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from conclaude import __author__, __description__, __title__, __url__, __version__

# The lowest error level makes the smallest code that holds the address, and a
# code on a screen loses none of its modules.
QR_ERROR: Final = "L"
# The quiet zone a reader needs around the code, in modules.
QR_BORDER: Final = 2


def qr_of(url: str) -> str:
    """``url`` as a QR code, in half-block glyphs: two rows of modules per line."""
    return render_qr(url, error=QR_ERROR, border=QR_BORDER)


def about_text() -> str:
    """What the About box says: the name, the version, the owner, the address.

    The address comes twice: as a QR code to point a phone at, and under it
    as text to read.
    """
    return "\n".join(
        [
            f"{__title__} {__version__}",
            __description__,
            f"Copyright © 2026 {__author__}",
            qr_of(__url__),
            __url__,
        ]
    )


class AboutScreen(ModalScreen[None]):
    """A box over the panes: what this tool is, and where it lives.

    The box only shows. It changes nothing. Any of its keys closes it, and
    the pane below has the focus again.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("question_mark", "close", "Close", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.text = about_text()

    def compose(self) -> ComposeResult:
        box = VerticalScroll(id="about")
        box.border_title = "About"
        with box:
            yield Static(self.text, id="about-text", markup=False)
        yield Footer()

    def action_close(self) -> None:
        """The box goes, and the pane that opened it has the focus again."""
        self.dismiss(None)
