"""``conclaude list`` and ``conclaude info``: a thin shell over the session store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from conclaude import __version__
from conclaude.core.errors import ConclaudeError
from conclaude.core.format import Formatter
from conclaude.core.model import Session, SessionDetails
from conclaude.core.settings import Settings
from conclaude.core.store import SessionStore

TITLE_WIDTH = 48


def titled(session: Session, fmt: Formatter) -> str:
    """The title with its marks, cut to the table width."""
    text = session.title
    tag = fmt.marks(session)
    if tag:
        text = f"{text} {tag}"
    if len(text) > TITLE_WIDTH:
        text = text[: TITLE_WIDTH - 3].rstrip() + "..."
    return text


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for the ``conclaude`` command."""
    defaults = Settings()
    parser = argparse.ArgumentParser(
        prog="conclaude",
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
        help=f"conclaude's own folder for the Trash and the cache (default: {defaults.data_dir})",
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
            fmt.timestamp(session.last_used),
            fmt.size(session.size),
            titled(session, fmt),
            session.project_path,
        )
        for session in sessions
    ]
    header = ("ID", "LAST USED", "SIZE", "TITLE", "PROJECT")
    widths = [max(len(row[i]) for row in (header, *rows)) for i in range(4)]
    for row in (header, *rows):
        cells = [row[i].ljust(widths[i]) for i in range(4)]
        print("  ".join(cells + [row[4]]).rstrip())
    total = sum(session.size for session in sessions)
    noun = "session" if len(sessions) == 1 else "sessions"
    print()
    print(f"{len(sessions)} {noun}, {fmt.size(total)} on disk")
    return 0


def _info_lines(details: SessionDetails, fmt: Formatter) -> list[tuple[str, str]]:
    session = details.session
    lines = [
        ("Id", session.id),
        ("Title", f"{session.title}  (from {session.title_source})"),
        ("Project", f"{session.project_path}  (from {session.project_source})"),
        ("Folder", session.project_key),
        ("Git branch", session.git_branch or "-"),
        ("Created", fmt.timestamp(session.created)),
        ("Last used", fmt.timestamp(session.last_used)),
        ("Claude Code", session.version or "-"),
        (
            "Transcript",
            f"{fmt.size(session.transcript_size)}  {session.transcript_path}",
        ),
    ]
    if session.sidecar_path is not None:
        agents = session.subagent_count
        noun = "subagent transcript" if agents == 1 else "subagent transcripts"
        lines.append(
            (
                "Sidecar",
                f"{fmt.size(session.sidecar_size)}  {session.sidecar_path}  ({agents} {noun})",
            )
        )
    else:
        lines.append(("Sidecar", "none"))
    lines.append(("Total", fmt.size(session.size)))
    if session.is_fork:
        lines.append(("Fork of", session.fork_parent or "-"))
        lines.append(
            ("Inherited", f"{fmt.size(details.inherited_bytes)} came from the parent")
        )
    lines.append(("Live", f"yes  (pid {session.pid})" if session.live else "no"))
    lines.append(("Damaged", "yes" if session.damaged else "no"))
    return lines


def cmd_info(store: SessionStore, args: argparse.Namespace, fmt: Formatter) -> int:
    """Print one session in full."""
    details = store.details(args.session_id)
    if args.json:
        print(json.dumps(details.to_dict(), indent=2))
        return 0
    lines = _info_lines(details, fmt)
    width = max(len(label) for label, _ in lines) + 1
    for label, value in lines:
        print(f"{(label + ':').ljust(width)} {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line. Returns the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    settings = settings_from(args)
    store = SessionStore(settings)
    fmt = Formatter(settings)
    try:
        if args.command == "list":
            return cmd_list(store, args, fmt)
        if args.command == "info":
            return cmd_info(store, args, fmt)
    except ConclaudeError as error:
        print(f"conclaude: {error}", file=sys.stderr)
        return 1
    parser.error(f"unknown command {args.command}")
