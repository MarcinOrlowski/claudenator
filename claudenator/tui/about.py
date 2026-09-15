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

from collections.abc import Callable
from typing import Final

from qrcat import render_qr
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from claudenator import __author__, __description__, __title__, __url__, __version__
from claudenator.tui.panes import key_help

# The lowest error level makes the smallest code that holds the address
QR_ERROR: Final = "L"
# The quiet zone a reader needs around the QR code, in modules.
QR_BORDER: Final = 2


def qr_of(url: str) -> str:
    """``url`` as a QR code, in half-block glyphs: two rows of modules per line."""
    return render_qr(url, error=QR_ERROR, border=QR_BORDER)


def about_text() -> str:
    """Content of the About box."""
    return "\n".join(
        [
            f"{__title__} {__version__}",
            __description__,
            f"Copyright © 2026 {__author__}",
            qr_of(__url__),
            __url__,
        ]
    )


def key_text(name_of: Callable[[Binding], str]) -> str:
    """Every key of the tool, by group: the title, then one key to a line.

    The footer lists only some of the keys, so this is where a new user finds
    the rest. The keys line up in one column, so the box stays narrow.
    """
    groups = [
        (title, [(name_of(binding), binding.description) for binding in bindings])
        for title, bindings in key_help()
    ]
    width = max(len(key) for _title, rows in groups for key, _what in rows)
    lines: list[str] = []
    for title, rows in groups:
        lines.append(title)
        lines += [f"  {key.ljust(width)}  {what}" for key, what in rows]
    return "\n".join(lines)


class AboutScreen(ModalScreen[None]):
    """About popup"""

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
        with box, Horizontal(id="about-columns"):
            yield Static(self.text, id="about-text", markup=False)
            # The app says how a key reads, so the box and the footer agree.
            keys = key_text(self.app.get_key_display)
            yield Static(keys, id="about-keys", markup=False)
        yield Footer()

    def action_close(self) -> None:
        """The box goes, and the pane that opened it has the focus again."""
        self.dismiss(None)
