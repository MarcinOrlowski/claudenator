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
    """Every key of the tool"""
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


class CloseKey(Static):
    """The X that closes the About box."""

    def __init__(self, hint: str) -> None:
        super().__init__(hint, id="about-close", markup=False)

    def on_click(self) -> None:
        """A click closes the About box."""
        self.screen.dismiss(None)


class AboutScreen(ModalScreen[None]):
    """About popup"""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("question_mark", "close", "Close", show=False),
    ]

    # The 'close' mark
    CLOSE_HINT = "[x]"

    # How far from the right edge the mark starts
    MARK_ROOM = len(CLOSE_HINT) + 2

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
        yield CloseKey(self.CLOSE_HINT)
        yield Footer()

    def on_mount(self) -> None:
        """The box has no size yet."""
        self.call_after_refresh(self._place_mark)

    def on_resize(self) -> None:
        """A new window size moves the box."""
        self.call_after_refresh(self._place_mark)

    def _place_mark(self) -> None:
        """Put the mark on the top/right part of the frame."""
        frame = self.query_one("#about").region
        mark = self.query_one(CloseKey)
        mark.offset = (frame.right - self.MARK_ROOM, frame.y)

    def action_close(self) -> None:
        """The box goes, and the pane that opened it has the focus again."""
        self.dismiss(None)
