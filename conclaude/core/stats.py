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

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conclaude.core.model import Figures
from conclaude.core.scan import parse_record, is_human_message, parse_timestamp

# The model name Claude Code puts on a message it made itself, with no API call:
# an error notice, an interruption. Such a message is not counted anywhere.
SYNTHETIC_MODEL = "<synthetic>"
TOKEN_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "cache_creation_input_tokens": "cache_write_tokens",
}
UNNAMED_TOOL = "?"


@dataclass
class Tally:
    """The running count while a transcript is read."""

    turns: int = 0
    tokens: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    tools: Counter[str] = field(default_factory=Counter)
    first_at: datetime | None = None
    last_at: datetime | None = None
    # One API answer is written as one record per content block, and every
    # one of them repeats the message id, the model and the usage. The ids
    # seen so far keep an answer from counting more than once.
    seen_messages: set[str] = field(default_factory=set)
    seen_tools: set[str] = field(default_factory=set)

    def take(self, record: dict[str, Any]) -> None:
        """Count one record."""
        moment = parse_timestamp(record.get("timestamp"))
        if moment is not None:
            if self.first_at is None or moment < self.first_at:
                self.first_at = moment
            if self.last_at is None or moment > self.last_at:
                self.last_at = moment
        if is_human_message(record):
            self.turns += 1
        elif record.get("type") == "assistant":
            self._take_assistant(record)

    def _take_assistant(self, record: dict[str, Any]) -> None:
        message = record.get("message")
        if not isinstance(message, dict):
            return
        model = message.get("model")
        if record.get("isApiErrorMessage") or model == SYNTHETIC_MODEL:
            return
        message_id = message.get("id")
        first_sight = True
        if isinstance(message_id, str):
            first_sight = message_id not in self.seen_messages
            self.seen_messages.add(message_id)
        if first_sight:
            self._take_usage(message.get("usage"))
            if isinstance(model, str) and model:
                self.models[model] += 1
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._take_tool(block)

    def _take_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for source, target in TOKEN_FIELDS.items():
            value = usage.get(source)
            if isinstance(value, int) and not isinstance(value, bool):
                self.tokens[target] += value

    def _take_tool(self, block: dict[str, Any]) -> None:
        tool_id = block.get("id")
        if isinstance(tool_id, str):
            if tool_id in self.seen_tools:
                return
            self.seen_tools.add(tool_id)
        name = block.get("name")
        self.tools[name if isinstance(name, str) and name else UNNAMED_TOOL] += 1


def ranked(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    """The names and their counts, biggest first, then by name."""
    return tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def deep_scan(transcript: Path, now: datetime | None = None) -> Figures:
    """Read the whole transcript, line by line, and count what it holds.

    Costly: every line is parsed. Never run at start-up or while a list
    is built. The size and change time are taken before the read, so a
    file that grows while it is read shows as stale on the next look.
    Raises ``OSError`` when the file cannot be read.
    """
    stat = transcript.stat()
    tally = Tally()
    with open(transcript, "rb") as handle:
        for raw in handle:
            record = parse_record(raw)
            if record is not None:
                tally.take(record)
    return Figures(
        transcript_path=transcript,
        transcript_size=stat.st_size,
        transcript_mtime_ns=stat.st_mtime_ns,
        scanned_at=now if now is not None else datetime.now(timezone.utc),
        turns=tally.turns,
        input_tokens=tally.tokens["input_tokens"],
        output_tokens=tally.tokens["output_tokens"],
        cache_read_tokens=tally.tokens["cache_read_tokens"],
        cache_write_tokens=tally.tokens["cache_write_tokens"],
        models=ranked(tally.models),
        tools=ranked(tally.tools),
        first_at=tally.first_at,
        last_at=tally.last_at,
    )
