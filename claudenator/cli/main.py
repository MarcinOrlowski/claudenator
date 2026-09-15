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

import argparse
import json
import sys
from pathlib import Path

from claudenator import __version__
from claudenator.core.errors import ClaudenatorError
from claudenator.core.format import Formatter, plural_of
from claudenator.core.model import Session
from claudenator.core.settings import Settings
from claudenator.core.store import SessionStore

TITLE_WIDTH = 48


def short_title(session: Session) -> str:
    """The title in truncated form."""
    text = session.title
    if len(text) > TITLE_WIDTH:
        text = text[: TITLE_WIDTH - 3].rstrip() + "…"
    return text


def open_screen(settings: Settings) -> int:
    """Run the TUI."""
    from claudenator.tui.app import run

    return run(settings)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for the ``claudenator`` command."""
    defaults = Settings()
    parser = argparse.ArgumentParser(
        prog="claudenator",
        description="Look at Claude Code sessions and remove the ones you do not want.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--claude-dir",
        type=Path,
        metavar="DIR",
        help=f"Claude Code's data folder (default: {defaults.claude_dir})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        metavar="DIR",
        help=f"claudenator's own folder for the Trash and the cache (default: {defaults.data_dir})",
    )
    # The process table. Only a test points this anywhere but /proc.
    parser.add_argument("--proc-dir", type=Path, metavar="DIR", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    list_parser = commands.add_parser("list", help="list every session")
    list_parser.add_argument("--json", action="store_true", help="print JSON")

    info_parser = commands.add_parser("info", help="show one session in full")
    info_parser.add_argument(
        "session_id", metavar="ID", help="a session id, or a unique prefix of one"
    )
    info_parser.add_argument("--json", action="store_true", help="print JSON")

    scan_parser = commands.add_parser(
        "scan", help="read every transcript in full and cache its figures"
    )
    scan_parser.add_argument(
        "--force",
        action="store_true",
        help="read a transcript again even when its cached figures are fresh",
    )
    return parser


def settings_from(args: argparse.Namespace) -> Settings:
    """A settings object with the command-line overrides applied."""
    settings = Settings()
    if args.claude_dir is not None:
        settings.claude_dir = args.claude_dir.expanduser()
    if args.data_dir is not None:
        settings.data_dir = args.data_dir.expanduser()
    if args.proc_dir is not None:
        settings.proc_dir = args.proc_dir.expanduser()
    return settings


def cmd_list(store: SessionStore, args: argparse.Namespace, fmt: Formatter) -> int:
    """Print every session, one per line."""
    sessions = store.list_sessions()
    if args.json:
        print(json.dumps([session.to_dict() for session in sessions], indent=2))
        return 0
    if not sessions:
        print(f"No sessions found under {store.settings.claude_dir}")
        return 0
    rows = [
        (
            session.id[:8],
            fmt.marks(session),
            fmt.list_timestamp(session.last_used),
            fmt.size(session.size),
            short_title(session),
            session.project_path,
        )
        for session in sessions
    ]
    header = ("ID", "STS", "LAST USED", "SIZE", "TITLE", "PROJECT")
    widths = [max(len(row[i]) for row in (header, *rows)) for i in range(5)]
    for row in (header, *rows):
        cells = [row[i].ljust(widths[i]) for i in range(5)]
        print("  ".join(cells + [row[5]]).rstrip())
    total = sum(session.size for session in sessions)
    noun = "session" if len(sessions) == 1 else "sessions"
    print()
    print(f"{len(sessions)} {noun}, {fmt.size(total)} on disk")
    return 0


def cmd_info(store: SessionStore, args: argparse.Namespace, fmt: Formatter) -> int:
    """Print one session in full."""
    details = store.details(args.session_id)
    if args.json:
        print(json.dumps(details.to_dict(), indent=2))
        return 0
    lines = fmt.describe(details)
    width = max(len(label) for label, _ in lines) + 1
    for label, value in lines:
        print(f"{(label + ':').ljust(width)} {value}")
    return 0


def cmd_scan(store: SessionStore, args: argparse.Namespace, fmt: Formatter) -> int:
    """Deep-scan every session and cache the figures. One line per session."""
    sessions = store.list_sessions()
    if not sessions:
        print(f"No sessions found under {store.settings.claude_dir}")
        return 0
    read = kept = failed = 0
    for result in store.scan_many(sessions, force=args.force):
        short = result.session.id[:8]
        if result.error is not None or result.figures is None:
            failed += 1
            print(f"{short}  {result.error}", file=sys.stderr)
            continue
        figures = result.figures
        if result.fresh:
            kept += 1
        else:
            read += 1
        turns = f"{fmt.count(figures.turns)} {plural_of('turn', figures.turns)}"
        tokens = f"{fmt.count(figures.tokens)} {plural_of('token', figures.tokens)}"
        length = fmt.duration(figures.duration)
        state = "cached" if result.fresh else "scanned"
        print(f"{short}  {turns}  {tokens}  {length}  {state}")
    dropped = store.cache.forget_missing()
    print()
    print(
        f"{fmt.scan_summary(read, kept, failed)}, "
        f"{dropped} gone from the disk and forgotten"
    )
    print(f"Cache: {store.settings.cache_file}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line. Returns the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings_from(args)
    if args.command is None:
        return open_screen(settings)
    store = SessionStore(settings)
    fmt = Formatter(settings)
    try:
        if args.command == "list":
            return cmd_list(store, args, fmt)
        if args.command == "info":
            return cmd_info(store, args, fmt)
        if args.command == "scan":
            return cmd_scan(store, args, fmt)
    except ClaudenatorError as error:
        print(f"claudenator: {error}", file=sys.stderr)
        return 1
    parser.error(f"unknown command {args.command}")
