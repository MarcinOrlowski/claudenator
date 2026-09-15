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

import os
import tracemalloc
from datetime import datetime, timezone

import pytest

from conclaude.core.errors import AmbiguousSessionId, ScanFailed, SessionNotFound
from conclaude.core.settings import Settings
from conclaude.core.store import SORT_COLUMNS, SessionStore, sort_key
from tests.fabricate import (
    FakeClaude,
    answer_records,
    dump_line,
    encode_project,
    new_id,
    prompt_record,
    session_records,
)

PROJECT = "/home/u/dev/app"


def test_lists_a_session_with_its_cheap_fields(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Lists a session with its cheap fields."""
    sid = new_id()
    records = session_records(
        sid, PROJECT, custom_title="Fix login", branch="feat/login"
    )
    path = fake.transcript(PROJECT, sid, records, mtime=1_789_000_000)
    fake.sidecar(PROJECT, sid, agents=2, bytes_each=500)

    [session] = store.list_sessions()

    assert session.id == sid
    assert session.title == "Fix login"
    assert session.title_source == "custom-title"
    assert session.project_path == PROJECT
    assert session.project_source == "transcript"
    assert session.project_key == "-home-u-dev-app"
    assert session.git_branch == "feat/login"
    assert session.version == "2.1.270"
    assert session.created == datetime(
        2026, 9, 14, 7, 18, 50, 439000, tzinfo=timezone.utc
    )
    assert session.last_used == datetime.fromtimestamp(1_789_000_000, tz=timezone.utc)
    assert session.transcript_size == path.stat().st_size
    assert session.sidecar_size == 2 * 500 + 2 * len(b"{}")
    assert session.size == session.transcript_size + session.sidecar_size
    assert session.subagent_count == 2
    assert session.sidecar_path == path.with_suffix("")
    assert not session.is_fork
    assert not session.damaged
    assert not session.live


def test_a_session_without_a_sidecar(fake: FakeClaude, store: SessionStore) -> None:
    """A session without a sidecar."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)

    [session] = store.list_sessions()

    assert session.sidecar_path is None
    assert session.sidecar_size == 0
    assert session.subagent_count == 0
    assert session.size == path.stat().st_size


def test_the_last_custom_title_wins(fake: FakeClaude, store: SessionStore) -> None:
    """The last custom title wins."""
    sid = new_id()
    records = session_records(sid, PROJECT, custom_title="first name")
    records.append(
        {"type": "custom-title", "customTitle": "second name", "sessionId": sid}
    )
    fake.transcript(PROJECT, sid, records)

    [session] = store.list_sessions()

    assert session.title == "second name"


def test_title_falls_back_to_the_first_human_message_not_the_boilerplate(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Title falls back to the first human message not the boilerplate."""
    sid = new_id()
    records = session_records(
        sid, PROJECT, human="Why is CI red?", last_prompt="a later one"
    )
    fake.transcript(PROJECT, sid, records)

    [session] = store.list_sessions()

    assert session.title == "Why is CI red?"
    assert session.title_source == "human"


def test_title_reads_a_message_made_of_blocks(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Title reads a message made of blocks."""
    sid = new_id()
    blocks = [{"type": "text", "text": "Look at this"}, {"type": "image", "source": {}}]
    fake.transcript(PROJECT, sid, session_records(sid, PROJECT, human=blocks))

    [session] = store.list_sessions()

    assert session.title == "Look at this"


def test_title_falls_back_to_the_last_prompt(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Title falls back to the last prompt."""
    sid = new_id()
    records = session_records(sid, PROJECT, human=None, last_prompt="/compact   please")
    fake.transcript(PROJECT, sid, records)

    [session] = store.list_sessions()

    assert session.title == "/compact please"
    assert session.title_source == "last-prompt"


def test_title_falls_back_to_the_id(fake: FakeClaude, store: SessionStore) -> None:
    """Title falls back to the id."""
    sid = new_id()
    fake.transcript(PROJECT, sid, session_records(sid, PROJECT, human=None))

    [session] = store.list_sessions()

    assert session.title == sid[:8]
    assert session.title_source == "id"


def test_title_is_one_line_and_bounded(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """Title is one line and bounded."""
    sid_short, sid_long = new_id(), new_id()
    fake.transcript(
        PROJECT,
        sid_short,
        session_records(sid_short, PROJECT, human="  many\n\nlines\there "),
    )
    fake.transcript(
        PROJECT, sid_long, session_records(sid_long, PROJECT, human="word " * 100)
    )

    titles = {session.id: session.title for session in store.list_sessions()}

    assert titles[sid_short] == "many lines here"
    assert len(titles[sid_long]) == settings.title_max_length
    assert titles[sid_long].endswith("...")


def test_project_path_comes_from_history_when_the_transcript_has_no_cwd(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Project path comes from history when the transcript has no cwd."""
    sid = new_id()
    records = session_records(sid, PROJECT)
    for record in records:
        record.pop("cwd", None)
    fake.transcript(PROJECT, sid, records)
    fake.history(sid, "/real/path/from/history")

    [session] = store.list_sessions()

    assert session.project_path == "/real/path/from/history"
    assert session.project_source == "history"


def test_project_path_falls_back_to_the_folder_name_as_a_label(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Project path falls back to the folder name as a label."""
    sid = new_id()
    records = session_records(sid, PROJECT)
    for record in records:
        record.pop("cwd", None)
    fake.transcript(PROJECT, sid, records)
    fake.history(new_id(), "/some/other/session")

    [session] = store.list_sessions()

    assert session.project_path == "-home-u-dev-app"
    assert session.project_source == "label"


def test_two_paths_that_share_one_folder_are_two_projects(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Two paths that share one folder are two projects."""
    path_a, path_b = "/home/u/a-b", "/home/u/a/b"
    assert encode_project(path_a) == encode_project(path_b)
    sid_a, sid_b = new_id(), new_id()
    fake.transcript(path_a, sid_a, session_records(sid_a, path_a), mtime=1_700_000_000)
    fake.transcript(path_b, sid_b, session_records(sid_b, path_b), mtime=1_800_000_000)
    fake.sidecar(path_b, sid_b, bytes_each=10)

    projects = store.list_projects()

    assert [project.path for project in projects] == [path_a, path_b]
    assert all(project.keys == ("-home-u-a-b",) for project in projects)
    assert [session.id for project in projects for session in project.sessions] == [
        sid_a,
        sid_b,
    ]
    assert projects[1].size == projects[1].sessions[0].size
    assert projects[1].last_used == datetime.fromtimestamp(
        1_800_000_000, tz=timezone.utc
    )


def test_skips_what_is_not_a_project_or_a_session(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Skips what is not a project or a session."""
    fake.lost_and_found("projects")
    (fake.root / "projects" / "notes.txt").write_text("not a folder")
    odd = fake.root / "projects" / "some dir!"
    odd.mkdir()
    (odd / f"{new_id()}.jsonl").write_bytes(b"{}\n")
    good = fake.project(PROJECT)
    (good / "memory").mkdir()
    (good / "memory" / "MEMORY.md").write_text("not a sidecar")
    (good / "agent-0123456789abcdef0.jsonl").write_bytes(b"{}\n")
    (good / "notes.jsonl").write_bytes(b"{}\n")
    fake.project("/home/u/empty")
    sid = new_id()
    fake.transcript(PROJECT, sid)

    assert [session.id for session in store.list_sessions()] == [sid]
    assert [project.path for project in store.list_projects()] == [PROJECT]


def test_a_bad_line_is_skipped_and_the_rest_still_reports(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A bad line is skipped and the rest still reports."""
    sid = new_id()
    records: list = session_records(sid, PROJECT, custom_title="Still fine")
    records.insert(1, b"this is not json\n")
    records.insert(4, b"\x00\xff\xfe garbage\n")
    fake.transcript(PROJECT, sid, records)

    [session] = store.list_sessions()

    assert session.title == "Still fine"
    assert session.project_path == PROJECT
    assert not session.damaged


def test_a_transcript_with_no_readable_line_is_listed_as_damaged(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A transcript with no readable line is listed as damaged."""
    sid = new_id()
    raw = b"\xff\xfe\x00 not json at all\n\x01\x02\n"
    fake.transcript(PROJECT, sid, raw=raw)

    [session] = store.list_sessions()

    assert session.damaged
    assert session.title == sid[:8]
    assert session.project_source == "label"
    assert session.size == len(raw)


def test_an_empty_transcript_is_not_damaged(
    fake: FakeClaude, store: SessionStore
) -> None:
    """An empty transcript is not damaged."""
    sid = new_id()
    fake.transcript(PROJECT, sid, raw=b"")

    [session] = store.list_sessions()

    assert not session.damaged
    assert session.title == sid[:8]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_a_transcript_that_cannot_be_opened_is_listed_as_damaged(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A transcript that cannot be opened is listed as damaged."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    path.chmod(0)
    try:
        [session] = store.list_sessions()
    finally:
        path.chmod(0o600)

    assert session.damaged
    assert session.size == path.stat().st_size


def test_a_fork_is_marked_and_its_inherited_bytes_are_reported(
    fake: FakeClaude, store: SessionStore
) -> None:
    """A fork is marked and its inherited bytes are reported."""
    parent, child = new_id(), new_id()
    fake.transcript(
        PROJECT, parent, session_records(parent, PROJECT, human="Original question")
    )
    copied = session_records(
        child, PROJECT, human="Original question", copied_from=parent
    )
    own = session_records(
        child, PROJECT, human="Question after the fork", custom_title="Forked"
    )
    path = fake.transcript(PROJECT, child, copied + own)

    sessions = {session.id: session for session in store.list_sessions()}
    fork = sessions[child]

    assert not sessions[parent].is_fork
    assert fork.is_fork
    assert fork.fork_parent == parent
    assert fork.size == path.stat().st_size

    details = store.details(child)
    expected = sum(len(dump_line(r)) for r in copied if r.get("session_id") == parent)
    assert 0 < expected < fork.size
    assert details.inherited_bytes == expected
    assert store.details(parent).inherited_bytes == 0


def test_a_transcript_is_streamed_never_loaded_whole(
    fake: FakeClaude, settings: Settings
) -> None:
    """A transcript is streamed never loaded whole."""
    sid = new_id()
    big = "x" * (64 * 1024)
    records: list = session_records(sid, PROJECT, custom_title="early")
    records += [
        {
            "type": "assistant",
            "uuid": new_id(),
            "message": {"role": "assistant", "content": big},
            "sessionId": sid,
            "session_id": sid,
        }
        for _ in range(200)
    ]
    records += [
        {"type": "custom-title", "customTitle": "the end", "sessionId": sid},
        {
            "type": "last-prompt",
            "lastPrompt": "bye",
            "leafUuid": new_id(),
            "sessionId": sid,
        },
    ]
    path = fake.transcript(PROJECT, sid, records)
    assert path.stat().st_size > 12 * 1024 * 1024

    tracemalloc.start()
    try:
        [session] = SessionStore(settings).list_sessions()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert session.title == "the end"
    assert (
        peak < 2 * 1024 * 1024
    ), f"peak {peak} bytes for a {path.stat().st_size} byte file"


def test_the_tail_read_grows_past_a_huge_last_record(
    fake: FakeClaude, store: SessionStore, settings: Settings
) -> None:
    """The tail read grows past a huge last record."""
    sid = new_id()
    records: list = session_records(sid, PROJECT, custom_title="early")
    records.append(
        {"type": "custom-title", "customTitle": "behind a big record", "sessionId": sid}
    )
    records.append(
        {
            "type": "assistant",
            "uuid": new_id(),
            "message": {
                "role": "assistant",
                "content": "x" * (settings.tail_bytes * 3),
            },
            "sessionId": sid,
            "session_id": sid,
        }
    )
    fake.transcript(PROJECT, sid, records)

    [session] = store.list_sessions()

    assert session.title == "behind a big record"


def test_find_session_by_a_unique_prefix_and_refuse_to_guess(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Find session by a unique prefix and refuse to guess."""
    sid_a = "aaaaaaaa-0000-4000-8000-000000000001"
    sid_b = "aaaaaaaa-0000-4000-8000-000000000002"
    fake.transcript(PROJECT, sid_a)
    fake.transcript(PROJECT, sid_b)

    assert store.find_session(sid_a).id == sid_a
    assert store.find_session(sid_b[:-1] + "2").id == sid_b
    assert store.get_session(sid_a).id == sid_a
    assert store.get_session("aaaaaaaa") is None
    with pytest.raises(AmbiguousSessionId, match="matches 2 sessions"):
        store.find_session("aaaa")
    with pytest.raises(SessionNotFound, match="no session matches 'zzzz'"):
        store.find_session("zzzz")


def test_default_order_is_last_used_newest_first(
    fake: FakeClaude, store: SessionStore
) -> None:
    """Default order is last used newest first."""
    older, newer = new_id(), new_id()
    fake.transcript(PROJECT, older, mtime=1_700_000_000)
    fake.transcript(PROJECT, newer, mtime=1_800_000_000)

    assert [session.id for session in store.list_sessions()] == [newer, older]


def test_sort_order_comes_from_the_settings(
    fake: FakeClaude, settings: Settings
) -> None:
    """Sort order comes from the settings."""
    settings.sort_column = "title"
    settings.sort_descending = False
    sid_a, sid_b = new_id(), new_id()
    fake.transcript(
        PROJECT, sid_a, session_records(sid_a, PROJECT, custom_title="beta")
    )
    fake.transcript(
        PROJECT, sid_b, session_records(sid_b, PROJECT, custom_title="alpha")
    )

    titles = [session.title for session in SessionStore(settings).list_sessions()]

    assert titles == ["alpha", "beta"]


def test_any_column_can_sort(fake: FakeClaude, settings: Settings) -> None:
    """Any column can sort. An unknown column keeps last used, and so does Msgs with
    nothing scanned yet.
    """
    older, newer = new_id(), new_id()
    fake.transcript(
        "/p/z",
        older,
        session_records(
            older, "/p/z", custom_title="beta", started="2026-09-14T06:00:00.000Z"
        ),
        mtime=1_700_000_000,
    )
    fake.transcript(
        "/p/a",
        newer,
        session_records(newer, "/p/a", custom_title="Alpha"),
        mtime=1_800_000_000,
    )
    fake.sidecar("/p/z", older, bytes_each=5000)
    sessions = SessionStore(settings).list_sessions()

    ordered = {
        column: [s.id for s in sorted(sessions, key=sort_key(column))]
        for column in (*SORT_COLUMNS, "nonsense")
    }

    assert [s.id for s in sessions] == [newer, older]
    # Neither session is live, a fork or damaged
    assert ordered["state"] == [newer, older]
    assert ordered["title"] == [newer, older]
    assert ordered["last_used"] == [older, newer]
    assert ordered["created"] == [older, newer]
    assert ordered["size"] == [newer, older]
    assert ordered["msgs"] == [older, newer]
    assert ordered["project"] == [newer, older]
    assert ordered["nonsense"] == [older, newer]


def test_msgs_orders_by_the_cached_turn_count_and_the_unscanned_go_last(
    fake: FakeClaude, settings: Settings
) -> None:
    """Msgs orders by the turn count in the figures given. A session with no
    figures orders below every scanned one, and below that by last use.
    """
    quiet, busy, unscanned = new_id(), new_id(), new_id()
    fake.transcript(PROJECT, quiet, session_records(quiet, PROJECT), mtime=1000)
    busy_records = session_records(busy, PROJECT) + [prompt_record(busy, "More")]
    fake.transcript(PROJECT, busy, busy_records, mtime=2000)
    fake.transcript(PROJECT, unscanned, mtime=3000)
    store = SessionStore(settings)
    sessions = store.list_sessions()
    for session in sessions:
        if session.id != unscanned:
            store.scan_of(session)
    figures = store.figures_for(sessions)

    biggest_first = sorted(sessions, key=sort_key("msgs", figures), reverse=True)

    assert set(figures) == {quiet, busy}
    assert [s.id for s in biggest_first] == [busy, quiet, unscanned]


def test_a_missing_claude_folder_lists_nothing(settings: Settings) -> None:
    """A missing claude folder lists nothing."""
    assert SessionStore(settings).list_sessions() == []
    assert SessionStore(settings).list_projects() == []


def test_details_take_the_figures_from_the_cache_and_never_scan(
    fake: FakeClaude, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Details carry the cached figures. With none cached they carry None, and no
    transcript is read in full for them.
    """
    sid = new_id()
    records = session_records(sid, PROJECT) + answer_records(sid, tools=["Bash"])
    fake.transcript(PROJECT, sid, records)
    store = SessionStore(settings)
    session = store.find_session(sid)

    before = store.details_of(session)
    scanned = store.scan_of(session)
    monkeypatch.setattr(
        "conclaude.core.store.deep_scan", lambda *_: pytest.fail("scanned again")
    )
    after = store.details_of(session)
    again = store.scan_of(session)

    assert before.figures is None
    assert before.to_dict()["figures"] is None
    assert after.figures == scanned
    assert after.figures is not None and after.figures.stale is False
    assert after.to_dict()["figures"]["turns"] == 1
    assert again == scanned


def test_a_scan_reads_again_when_the_transcript_changed_or_when_forced(
    fake: FakeClaude, settings: Settings
) -> None:
    """Fresh figures are handed back as they are. Stale ones are replaced by a new
    read, and so are fresh ones when the caller insists.
    """
    sid = new_id()
    path = fake.transcript(PROJECT, sid, session_records(sid, PROJECT))
    store = SessionStore(settings)
    session = store.find_session(sid)
    first = store.scan_of(session)

    with open(path, "ab") as handle:
        handle.write(dump_line(prompt_record(sid, "More")))
    stale = store.figures_of(session)
    second = store.scan_of(session)
    third = store.scan_of(session, force=True)

    assert first.turns == 1
    assert stale is not None and stale.stale is True and stale.turns == 1
    assert second.turns == 2 and second.stale is False
    assert third.turns == 2 and third.scanned_at >= second.scanned_at


def test_a_scan_of_an_unreadable_transcript_names_the_file(
    fake: FakeClaude, settings: Settings
) -> None:
    """A transcript that goes away between the list and the scan raises, with its path."""
    sid = new_id()
    path = fake.transcript(PROJECT, sid)
    store = SessionStore(settings)
    session = store.find_session(sid)
    path.unlink()

    with pytest.raises(ScanFailed, match="could not read") as caught:
        store.scan_of(session)

    assert caught.value.path == path
    assert caught.value.session_id == sid


def test_scan_many_gives_one_result_per_session_and_carries_on_past_a_failure(
    fake: FakeClaude, settings: Settings
) -> None:
    """Every session gives one result, in the order it was given."""
    cached, plain, gone = new_id(), new_id(), new_id()
    fake.transcript(PROJECT, cached, session_records(cached, PROJECT), mtime=3000)
    fake.transcript(PROJECT, plain, session_records(plain, PROJECT), mtime=2000)
    lost = fake.transcript(PROJECT, gone, session_records(gone, PROJECT), mtime=1000)
    store = SessionStore(settings)
    sessions = store.list_sessions()
    store.scan_of(store.find_session(cached))
    lost.unlink()

    results = list(store.scan_many(sessions))
    forced = list(store.scan_many(sessions, force=True))

    found = {result.session.id: result for result in results}
    assert [result.session.id for result in results] == [cached, plain, gone]
    assert found[cached].fresh is True
    assert found[cached].figures is not None and found[cached].figures.turns == 1
    assert found[plain].fresh is False
    assert found[plain].figures is not None and found[plain].figures.turns == 1
    assert found[gone].figures is None
    assert isinstance(found[gone].error, ScanFailed)
    assert [result.fresh for result in forced] == [False, False, False]


def test_a_deep_scan_never_holds_the_whole_transcript(
    fake: FakeClaude, settings: Settings
) -> None:
    """A deep scan reads line by line. Its peak memory stays far below the file size."""
    sid = new_id()
    big = "x" * 64 * 1024
    records: list = session_records(sid, PROJECT)
    records += [
        {
            "type": "assistant",
            "uuid": new_id(),
            "message": {"role": "assistant", "content": big},
            "sessionId": sid,
        }
        for _ in range(200)
    ]
    path = fake.transcript(PROJECT, sid, records)
    assert path.stat().st_size > 12 * 1024 * 1024
    store = SessionStore(settings)
    session = store.find_session(sid)

    tracemalloc.start()
    try:
        figures = store.scan_of(session)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert figures.turns == 1
    assert (
        peak < 2 * 1024 * 1024
    ), f"peak {peak} bytes for a {path.stat().st_size} byte file"
