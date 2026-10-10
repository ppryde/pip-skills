"""Incremental, idempotent ingest of transcripts into the chronicle store.

Every fact table is keyed by a transcript-native id (message id, tool_use id,
record uuid), and every write is ``INSERT OR IGNORE`` / ``INSERT OR REPLACE``
— so re-reading a file from byte 0 (after a rewrite, a lost cursor, or a
deliberate ``backfill``) converges on the same rows instead of double
counting. The per-session rollup on ``sessions`` is then recomputed from the
fact tables, never incremented.

``cursors`` remembers, per file, the byte offset after the last COMPLETE
line plus the file's mtime and size as last seen. ``sync`` (the on-demand
path the dashboard's Sync button drives) stats every transcript on disk,
touches only the files whose mtime/size moved, and parses only the bytes
appended since — so a sync over hundreds of transcripts is a directory walk
plus a handful of tail reads. The Stop hook uses the same ``ingest_session``
for a live feed, but nothing depends on it.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from scripts import replay, store
from scripts.transcript import MAIN_AGENT, Facts, Turn, fold
from scripts.volumes import RemoteSession, VolumeError, VolumeSource, group_sessions

_GIT_TIMEOUT_SECONDS = 2
_AGENT_FILE_RE = re.compile(r"^agent-(?P<agent>[^.]+)\.jsonl$")


# How far up from a recorded cwd we will look for a directory that exists here.
# Deep enough for the paths that actually go missing — a worktree under
# `<repo>/.claude/worktrees/<name>` is three levels down — and shallow enough
# that a wildly wrong path cannot climb to some unrelated repo far above it.
_ANCESTOR_LIMIT = 4


def resolve_on_host(cwd: str | None) -> str | None:
    """``cwd`` as a directory that exists on THIS machine, or None.

    A recorded cwd need not exist where the transcript is read. Two cases, and
    both used to yield no repo at all:

    1. **Another filesystem.** A containerised session records ``/workspaces/foo``;
       the host has it at ``~/repos/foo``. ``store.path_map`` rewrites the prefix.
    2. **A path since removed.** A git worktree under ``<repo>/.claude/worktrees/<name>``
       is deleted when the work lands, or exists only inside the container. The
       directory is gone but its PARENT repo is right there, and that is the
       answer the caller wants — a session is attributed to its repo, not to the
       working copy it happened to use.

    So: rewrite, then walk up to the nearest existing ancestor. The walk is
    bounded (``_ANCESTOR_LIMIT``) and its result still has to satisfy git in
    ``repo_root_of`` — an ancestor that is not a repo attributes nothing, which
    is what stops the walk turning a nonsense path into a confident wrong answer.
    """
    if not cwd:
        return None
    for src, dst in store.path_map():
        # Normalise BOTH sides before splicing. The boundary test tolerated a
        # trailing slash on the source, but the splice used the raw length —
        # so `/workspaces/app/` + `/workspaces/app/src` ate the separator and
        # produced `<host>src`. That path does not exist, the ancestor walk
        # below then climbed to a real but unrelated directory, and the
        # session was attributed to it with full confidence.
        src, dst = src.rstrip("/"), dst.rstrip("/")
        if cwd == src or cwd.startswith(src + "/"):
            cwd = dst + cwd[len(src):]
            break
    path = Path(cwd)
    for _ in range(_ANCESTOR_LIMIT + 1):
        parent = path.parent
        if parent == path:
            # The filesystem root. It exists on every machine, so accepting it
            # would turn any unrecognised absolute path into a confident "/"
            # — the exact wrong answer this walk is bounded to avoid.
            return None
        if path.is_dir():
            return str(path)
        path = parent
    return None


def repo_root_of(cwd: str | None) -> str | None:
    """The MAIN repo root ``cwd`` belongs to (worktrees resolve to their
    primary checkout via the shared git common dir), or None outside git /
    on any failure. Bounded so a stalled git never stalls a hook.

    ``cwd`` is first resolved onto this filesystem (see ``resolve_on_host``):
    it may name a container path, or a worktree that no longer exists."""
    cwd = resolve_on_host(cwd)
    if not cwd:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    common = result.stdout.strip()
    if not common:
        return None
    path = Path(common)
    if path.name == ".git":
        path = path.parent
    return str(path.resolve())


def project_slug_of(transcript_path: Path) -> str:
    return transcript_path.parent.name


def _read_new_lines(path: Path, offset: int) -> tuple[list[str], int, int]:
    """Lines appended after ``offset``, the new offset (after the last
    complete line), and the offset the read actually STARTED at. A file that
    shrank (rewritten) restarts from 0 — which is why the start is returned:
    a caller that seeds state from "what came before" needs to know whether
    this read has a "before" at all (see ``ingest_file``'s bridge owner)."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset, offset
    if offset > size:
        offset = 0
    if offset == size:
        return [], offset, offset
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], offset, offset
    lines, new_offset = _complete_lines(chunk, offset)
    return lines, new_offset, offset


def _complete_lines(chunk: bytes, offset: int) -> tuple[list[str], int]:
    """The COMPLETE lines in ``chunk`` (bytes read starting at ``offset``) and
    the offset after the last of them. A trailing partial line is left for the
    next read: the writer may still be mid-line. Shared by the local and the
    docker-volume readers so both cut lines identically."""
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return [], offset
    complete = chunk[: last_nl + 1]
    # Split on b"\n" only: str.splitlines() also cuts on U+0085/2028/2029, which
    # JSON.stringify leaves raw inside a record, fragmenting it into bad JSON.
    pieces = complete.split(b"\n")[:-1]
    return [p.decode("utf-8", errors="replace") for p in pieces], offset + len(complete)


def _cursor(conn: sqlite3.Connection, path: Path | str) -> int:
    row = conn.execute("SELECT byte_offset FROM cursors WHERE path = ?", (str(path),)).fetchone()
    return int(row[0]) if row else 0


def _stat(path: Path) -> tuple[float, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


def file_changed(conn: sqlite3.Connection, path: Path) -> bool:
    """Whether ``path``'s mtime or size differs from what the cursor last saw
    (a never-seen file counts as changed; a vanished one does not)."""
    current = _stat(path)
    if current is None:
        return False
    row = conn.execute("SELECT mtime, size FROM cursors WHERE path = ?", (str(path),)).fetchone()
    if row is None:
        return True
    return (float(row[0]), int(row[1])) != current


def _owned_elsewhere(conn: sqlite3.Connection, table: str, column: str,
                     ids: set[str], session_id: str) -> set[str]:
    """Ids from ``table`` already stored under a DIFFERENT session — the
    signal that a record is a copy, not new work (see ``_write_facts``).
    Batched to stay clear of SQLite's variable-count limit on a fat resume."""
    found: set[str] = set()
    ordered = sorted(ids)
    for start in range(0, len(ordered), 500):
        chunk = ordered[start:start + 500]
        marks = ",".join("?" * len(chunk))
        found.update(
            row[0] for row in conn.execute(
                f"SELECT {column} FROM {table} WHERE session_id <> ? AND {column} IN ({marks})",
                (session_id, *chunk),
            )
        )
    return found


def _resolve_replays(conn: sqlite3.Connection, session_id: str, turns: list[Turn],
                     snapshot_bytes: int) -> tuple[list[Turn], dict[str, str], list[tuple[str, str]]]:
    """Apply the one-call-one-row rule (see ``scripts.replay``) to a batch.

    A call may already be stored under ANOTHER agent (a resumed agent's later
    snapshot file, or a fork, repeats its history). Returns
    ``(turns to write, {message_id: surviving agent}, [(message_id, agent)] to
    adopt)``. A batch turn that loses is not written; one that wins deletes the
    other agents' rows first. ``snapshot_bytes`` is how far this batch's file has
    been read, which ranks this copy against the stored ones by snapshot length.
    """
    stored = replay.stored_copies(conn, session_id, [t.message_id for t in turns])
    keep: list[Turn] = []
    owner: dict[str, str] = {}
    adopt: list[tuple[str, str]] = []
    for t in turns:
        others = [c for c in stored.get(t.message_id, []) if c.agent_id != t.agent_id]
        if not others:
            keep.append(t)
            owner[t.message_id] = t.agent_id
            continue
        mine = replay.Copy(t.agent_id, t.output_tokens, t.stop_reason, snapshot_bytes)
        winner = replay.canonical([mine, *others])
        owner[t.message_id] = winner.agent_id
        replay.drop_all_but(conn, session_id, t.message_id, winner.agent_id)
        if winner is mine:
            keep.append(t)
        adopt.append((t.message_id, winner.agent_id))
    return keep, owner, adopt


def _write_facts(conn: sqlite3.Connection, session_id: str, facts: Facts,
                 snapshot_bytes: int = 0) -> None:
    # A resumed or forked transcript repeats records from the session it was
    # resumed/forked FROM, verbatim, under this new session id. Every id here
    # is otherwise globally unique, so a record already stored under another
    # session is a copy, not new work — counting it again would inflate every
    # total that aggregates across sessions by however much was repeated.
    # Whichever session's ingest reaches a record first keeps it: this is a
    # first-seen rule, not "parent always wins" — a copy synced before its
    # source claims the record, and the source then finds it already owned.
    copied_messages = _owned_elsewhere(
        conn, "turns", "message_id", {t.message_id for t in facts.turns.values()}, session_id
    )
    fresh = [t for t in facts.turns.values() if t.message_id not in copied_messages]
    # Within ONE session the same call can still appear in several files (a
    # resumed agent re-writes its history into a new file); it is one row.
    # `turns` are the rows this batch writes; `tool_turns` are every fresh
    # turn re-homed to the agent that OWNS its call, so a skipped copy's tool
    # uses, artifacts and edits are recorded once, under the surviving row.
    turns, owner, adopted = _resolve_replays(conn, session_id, fresh, snapshot_bytes)
    tool_turns = [t if owner[t.message_id] == t.agent_id else replace(t, agent_id=owner[t.message_id])
                  for t in fresh]
    tool_owner = {tool_id: t.agent_id for t in tool_turns for tool_id, _, _ in t.tool_uses}
    tool_ids = (
        {tool_id for t in tool_turns for tool_id, _, _ in t.tool_uses}
        | set(facts.results) | set(facts.file_edits)
    )
    copied_tools = _owned_elsewhere(conn, "tool_calls", "tool_use_id", tool_ids, session_id)
    copied_events = _owned_elsewhere(conn, "events", "uuid", {e.uuid for e in facts.events}, session_id)
    results = [r for r in facts.results.values() if r.tool_use_id not in copied_tools]
    # tool_calls rows first: a message split across two ingests (a Stop hook
    # or a dashboard Sync landing mid-write) folds into two DISJOINT Turn
    # objects, one per call, each seeing only the tool_use blocks that were
    # on disk at the time — so len(t.tool_uses) is only THIS batch's count,
    # not the message's total. tool_calls rows are keyed by tool_use_id, so
    # they accumulate correctly across ingests (the upsert below fills a
    # missing qualifier and changes nothing else); turns.tool_calls is then a
    # COUNT(*) against that already-correct table, not the batch-local len().
    conn.executemany(
        # Not INSERT OR IGNORE: a store ingested before `qualifier` existed has
        # the row already, so ignoring the conflict would leave it NULL forever
        # and `sync --full` would silently fail to backfill. COALESCE fills only
        # what is missing, and touches nothing else — `result_chars`/`result_ts`
        # are owned by the separate UPDATE below and must survive a re-sync.
        """INSERT INTO tool_calls(session_id, tool_use_id, agent_id, message_id,
               tool_name, qualifier, ts) VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(session_id, tool_use_id) DO UPDATE SET
               qualifier = COALESCE(tool_calls.qualifier, excluded.qualifier)""",
        [
            (session_id, tool_id, t.agent_id, t.message_id, name, qualifier, t.ts)
            for t in tool_turns
            for tool_id, name, qualifier in t.tool_uses
            if tool_id not in copied_tools
        ],
    )
    conn.executemany(
        """INSERT INTO turns(session_id, agent_id, message_id, request_id, ts, model,
               input_tokens, cache_read_tokens, cache_creation_tokens, output_tokens,
               thinking_tokens, cache_5m_tokens, cache_1h_tokens, tool_calls, stop_reason, effort,
               skill, plugin, agent_type, mcp_server, mcp_tool, account_uuid)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,
               (SELECT COUNT(*) FROM tool_calls
                WHERE session_id = ? AND message_id = ?),
               ?,?,?,?,?,?,?,?)
           ON CONFLICT(session_id, agent_id, message_id) DO UPDATE SET
               request_id = excluded.request_id, ts = excluded.ts, model = excluded.model,
               input_tokens = excluded.input_tokens, cache_read_tokens = excluded.cache_read_tokens,
               cache_creation_tokens = excluded.cache_creation_tokens,
               output_tokens = excluded.output_tokens, thinking_tokens = excluded.thinking_tokens,
               cache_5m_tokens = excluded.cache_5m_tokens, cache_1h_tokens = excluded.cache_1h_tokens,
               tool_calls = excluded.tool_calls, stop_reason = excluded.stop_reason,
               effort = excluded.effort,
               -- COALESCE, like tool_calls.qualifier: a store ingested before
               -- these columns existed has the row already, and overwriting
               -- with a fresh NULL would undo a backfill rather than do one.
               skill = COALESCE(excluded.skill, turns.skill),
               plugin = COALESCE(excluded.plugin, turns.plugin),
               agent_type = COALESCE(excluded.agent_type, turns.agent_type),
               mcp_server = COALESCE(excluded.mcp_server, turns.mcp_server),
               mcp_tool = COALESCE(excluded.mcp_tool, turns.mcp_tool),
               -- COALESCE for the same reason, and one more: a turn written
               -- before any bridge record legitimately carries NULL, which
               -- must never erase a stamp an earlier ingest already made.
               account_uuid = COALESCE(excluded.account_uuid, turns.account_uuid)""",
        [
            (session_id, t.agent_id, t.message_id, t.request_id, t.ts, t.model,
             t.input_tokens, t.cache_read_tokens, t.cache_creation_tokens, t.output_tokens,
             t.thinking_tokens, t.cache_5m_tokens, t.cache_1h_tokens,
             session_id, t.message_id,
             t.stop_reason, t.effort,
             t.skill, t.plugin, t.agent_type, t.mcp_server, t.mcp_tool, t.account_uuid)
            for t in turns
        ],
    )
    # A call that lost (or replaced) other copies: its tool rows and the
    # surviving turn's tool count are made to agree with the surviving agent.
    for message_id, agent_id in adopted:
        replay.adopt(conn, session_id, message_id, agent_id)
    conn.executemany(
        "INSERT OR IGNORE INTO events(session_id, uuid, agent_id, kind, ts, value) "
        "VALUES (?,?,?,?,?,?)",
        [(session_id, e.uuid, e.agent_id, e.kind, e.ts, e.value)
         for e in facts.events if e.uuid not in copied_events],
    )
    # Results may land in a later ingest than their call (a Stop hook fires
    # between the two), so this is an UPDATE against whatever row exists.
    conn.executemany(
        "UPDATE tool_calls SET result_chars = ?, result_ts = ? "
        "WHERE session_id = ? AND tool_use_id = ?",
        [(r.chars, r.ts, session_id, r.tool_use_id) for r in results],
    )
    # Keyed by tool_use_id like every other fact table, so a re-read of the
    # same transcript converges rather than double-counting the churn.
    conn.executemany(
        """INSERT OR REPLACE INTO file_edits(session_id, tool_use_id, agent_id, ts, file_path,
               operation, lines_added, lines_removed) VALUES (?,?,?,?,?,?,?,?)""",
        [
            (session_id, e.tool_use_id, tool_owner.get(e.tool_use_id, e.agent_id), e.ts, e.file_path, e.operation,
             e.lines_added, e.lines_removed)
            for e in facts.file_edits.values()
            if e.tool_use_id not in copied_tools
        ],
    )
    conn.executemany(
        """INSERT OR REPLACE INTO artifacts(session_id, tool_use_id, agent_id, ts, url, title,
               description, favicon, redeploy) VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (session_id, a.tool_use_id, t.agent_id, t.ts, a.url, a.title, a.description,
             a.favicon, int(a.redeploy))
            for t in tool_turns
            for a in t.artifacts.values()
            if a.tool_use_id not in copied_tools
        ],
    )
    # An artifact whose result landed in THIS ingest but whose call was
    # written by an earlier one (a Stop hook fired between them): fill the
    # url on the existing row.
    conn.executemany(
        "UPDATE artifacts SET url = ? WHERE session_id = ? AND tool_use_id = ? AND url IS NULL",
        [(r.artifact_url, session_id, r.tool_use_id)
         for r in results if r.artifact_url],
    )
    # Deliberately not filtered through `_owned_elsewhere` like every table
    # above: the SAME real-world hit is written into every session and
    # subagent running at the time BY DESIGN, and "how many sessions saw it"
    # is part of what `report.limits` reads back out. Keyed on the record's
    # own uuid, like `events`, so re-reading a file from byte 0 converges.
    conn.executemany(
        """INSERT OR IGNORE INTO limit_hits(session_id, agent_id, uuid, ts, kind, model,
               reset_raw, resets_at, raw_text) VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (session_id, h.agent_id, h.uuid, h.ts, h.kind, h.model,
             h.reset_raw, h.resets_at, h.raw_text)
            for h in facts.limit_hits
        ],
    )


class ProfileResolver:
    """``config_dir`` label -> the non-personal account facts it holds now.

    A host dir is read off this filesystem. A ``docker://<volume>`` label is
    read through the volume's helper container — lazily, and AT MOST ONCE per
    resolver (so once per sync, however many sessions ask), because each read
    is a container start. A volume whose sync failed is `disable`d: asking it
    again would just spend another docker timeout on a daemon known to be down.
    A label nobody registered (a volume since removed from the config) resolves
    to None without touching docker."""

    def __init__(self, volumes: Sequence[VolumeSource] = ()) -> None:
        self._volumes = {v.label: v for v in volumes}
        self._loaded: dict[str, dict[str, str] | None] = {}
        self.read: set[str] = set()      # labels a helper container was really asked

    def __call__(self, config_dir: str) -> dict[str, str] | None:
        if store.is_remote_label(config_dir):
            # A remote's mirror is an ordinary local dir (see scripts.remote):
            # reading its `.claude.json` is a plain file read, not a helper
            # container start, so this needs none of the lazy-once-per-sync
            # caching a volume's docker read does.
            mirror = store.remote_mirror_dir_for(config_dir)
            return store.account_profile(mirror) if mirror else None
        if not store.is_volume_label(config_dir):
            return store.account_profile(Path(config_dir))
        if config_dir not in self._loaded:
            source = self._volumes.get(config_dir)
            self._loaded[config_dir] = source.read_account() if source else None
            if source:
                self.read.add(config_dir)
        return self._loaded[config_dir]

    def probed(self, config_dir: str) -> bool:
        return config_dir in self._loaded

    def knows(self, config_dir: str) -> bool:
        return config_dir in self._volumes

    def disable(self, config_dir: str) -> None:
        self._loaded[config_dir] = None
        self.read.discard(config_dir)


ProfileOf = Callable[[str], "dict[str, str] | None"]


def _account_snapshot(conn: sqlite3.Connection, config_dir: str | None, now: float,
                      profile_of: ProfileOf | None = None,
                      ) -> tuple[dict[str, Any], str | None]:
    """The plan columns to stamp on a session, and the account uuid found —
    plus the `accounts` upsert that goes with it, as a side effect. `({}, None)`
    when the config dir holds no readable account.

    Read at INGEST time. The PLAN is stamped per session because it changes:
    an account that moves from Max to Enterprise would otherwise have every
    session it ever ran relabelled by the move. `plan_observed_at` records
    when the claim was true, so a row is legible as a snapshot rather than a
    standing fact. The ACCOUNT UUID itself does not change this way — an
    account keeps its uuid across plan moves — but the caller still treats it
    as write-once (see `_upsert_session_identity`): a session belongs to
    whichever account was logged in the FIRST time it was ingested, not to
    whoever happens to be logged into that config dir on a later resync.

    Only the identity half goes in `accounts` — the half that does not change.
    Everything read here is whitelisted by name in `store.account_profile`;
    nothing personal reaches the database.
    """
    if not config_dir:
        return {}, None
    profile = (profile_of or ProfileResolver())(config_dir)
    if not profile:      # None (no/unreadable file) or {} (API key: no oauthAccount)
        return {}, None
    account_uuid = profile.get("accountUuid")
    if account_uuid:
        conn.execute(
            """INSERT INTO accounts(account_uuid, organization_uuid, first_seen, last_seen)
                    VALUES (?,?,?,?)
               ON CONFLICT(account_uuid) DO UPDATE SET
                    organization_uuid = COALESCE(excluded.organization_uuid, organization_uuid),
                    last_seen = MAX(COALESCE(last_seen, 0), excluded.last_seen)""",
            (account_uuid, profile.get("organizationUuid"), now, now),
        )
    snapshot: dict[str, Any] = {
        column: profile[key]
        for key, column in store.ACCOUNT_PLAN_FIELDS.items()
        if profile.get(key)
    }
    if snapshot:
        snapshot["plan_observed_at"] = now
    return snapshot, account_uuid


def config_dir_of(transcript_path: Path) -> str | None:
    """The Claude config dir a main transcript belongs to, from its layout
    ``<config>/projects/<slug>/<session>.jsonl`` — None for any other shape
    (a test fixture, a copied file). A transcript read out of a configured
    remote's local mirror (see `scripts.remote`) is stamped with the stable
    ``remote://<name>`` label instead of the mirror's real path — the same
    trick WF-120 plays for `docker://<volume>`, and for the same reason: the
    mirror directory is an implementation detail of HOW the transcript got
    here, not a fact about the account it belongs to."""
    parents = transcript_path.resolve().parents
    if len(parents) >= 3 and parents[1].name == "projects":
        candidate = parents[2]
        return store.remote_label_for(candidate) or str(candidate)
    return None


@dataclass(frozen=True)
class _Origin:
    """Where a transcript file lives, as the store records it. For a host file
    ``key`` is its path; for a docker volume it is the synthetic
    ``docker://<volume>/<relpath>`` — never something to `Path()` or `stat()`."""
    key: str                      # the cursor key, and `sessions.transcript_path`
    slug: str
    config_dir: str | None
    description: str | None = None    # a subagent's short label, from its meta file


def _local_origin(path: Path, agent_id: str) -> _Origin:
    return _Origin(
        key=str(path), slug=project_slug_of(path), config_dir=config_dir_of(path),
        description=agent_description(path) if agent_id != MAIN_AGENT else None,
    )


def _upsert_session_identity(conn: sqlite3.Connection, session_id: str, facts: Facts,
                             origin: _Origin, now: float,
                             profile_of: ProfileOf | None = None) -> None:
    """Create the session row if absent, then fill identity columns from the
    facts without clobbering a known value with None."""
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, updated_at) VALUES (?, ?)",
        (session_id, now),
    )
    cwd = facts.cwd
    config = origin.config_dir
    updates: dict[str, Any] = {
        "project_slug": origin.slug,
        "transcript_path": origin.key,
        "config_dir": config,
        "cwd": cwd,
        "repo_root": repo_root_of(cwd) if cwd else None,
        "git_branch": facts.git_branch,
        "version": facts.version,
        "entrypoint": facts.entrypoint,
        "title": facts.title,
    }
    for column, value in updates.items():
        if value is None:
            continue
        conn.execute(
            f"UPDATE sessions SET {column} = ? WHERE session_id = ?", (value, session_id)
        )
    # Write-once, unlike every column above. The plan columns, account_uuid,
    # AND owner_account_uuid record what was true WHEN THE SESSION WAS FIRST
    # SEEN; re-stamping them on a later ingest would let `sync --full` quietly
    # relabel the whole back catalogue with today's login — destroying the
    # very history the snapshot exists to keep. Each is guarded on ITS OWN
    # column being unset, not a shared flag: a session ingested before
    # `account_uuid` existed already has `plan_observed_at` set, and sharing
    # one guard would leave it unbackfilled forever. So a session missing any
    # of them gets a fresh read (of the profile for plan/account_uuid, of this
    # batch's facts for owner_account_uuid), and each column is then written
    # only if IT is still unset — each keeps whichever value it saw first,
    # independently. owner_account_uuid needs the same guard as account_uuid
    # for the same reason: a bridged session's account CAN change mid-stream
    # (a real `/login` observed in the wild re-emits `bridge-session` with a
    # new `ownerAccountUuid`), and an incremental ingest that lands on the
    # switched-to account must not relabel the session's original owner.
    already = conn.execute(
        "SELECT plan_observed_at, account_uuid, owner_account_uuid FROM sessions "
        "WHERE session_id = ?", (session_id,)
    ).fetchone()
    plan_pending = already is None or already[0] is None
    account_pending = already is None or already[1] is None
    owner_pending = already is None or already[2] is None
    if plan_pending or account_pending:
        snapshot, account_uuid = _account_snapshot(conn, config, now, profile_of)
        if plan_pending:
            for column, value in snapshot.items():
                conn.execute(
                    f"UPDATE sessions SET {column} = ? WHERE session_id = ?", (value, session_id)
                )
        if account_pending and account_uuid:
            conn.execute(
                "UPDATE sessions SET account_uuid = ? WHERE session_id = ?",
                (account_uuid, session_id),
            )
    if owner_pending and facts.owner_account_uuid:
        conn.execute(
            "UPDATE sessions SET owner_account_uuid = ? WHERE session_id = ?",
            (facts.owner_account_uuid, session_id),
        )
    if facts.first_ts is not None:
        conn.execute(
            "UPDATE sessions SET started_at = MIN(COALESCE(started_at, ?), ?) WHERE session_id = ?",
            (facts.first_ts, facts.first_ts, session_id),
        )
    if facts.last_ts is not None:
        conn.execute(
            "UPDATE sessions SET last_activity_at = MAX(COALESCE(last_activity_at, 0), ?) "
            "WHERE session_id = ?",
            (facts.last_ts, session_id),
        )
        # A session the (since-removed) SessionEnd hook stamped as ended can
        # be RESUMED: new transcript lines after that stamp mean it is alive
        # again, so the stamp is lifted — otherwise ``is_live`` would read it
        # as ended for good. Nothing writes ``ended_at`` any more; liveness
        # is the activity horizon alone.
        conn.execute(
            "UPDATE sessions SET ended_at = NULL, end_reason = NULL "
            "WHERE session_id = ? AND ended_at IS NOT NULL AND last_activity_at > ended_at",
            (session_id,),
        )


def _initial_owner(conn: sqlite3.Connection, session_id: str, agent_id: str,
                   start_offset: int) -> str | None:
    """The bridge owner already in force where this read begins.

    A MAIN transcript read from byte 0 begins with no owner at all: the
    session's stored ``bridge_owner_uuid`` is the LAST owner it ever had, so
    seeding a from-the-top walk with it (a ``sync --full``) would stamp the
    turns before the first bridge record with an owner that did not exist yet.
    Mid-file, the bridge record may be in an earlier batch than the turns it
    governs, so the walk resumes from the stored owner.

    A SUBAGENT transcript holds no bridge records of its own and carries no
    position relative to the main file's, so its turns take whatever owner the
    session currently has — a documented approximation (see the README's
    "Account attribution")."""
    if agent_id == MAIN_AGENT and start_offset == 0:
        return None
    row = conn.execute(
        "SELECT bridge_owner_uuid FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row[0] if row else None


def _touch_cursor(conn: sqlite3.Connection, key: str, session_id: str, agent_id: str,
                  offset: int, stat: tuple[float, int], now: float) -> None:
    """Remember a file as seen with nothing new to parse, so a later sync does
    not re-stat it as "changed" (e.g. a touched-but-empty tail). An upsert, not
    a bare UPDATE: a file seen for the first time with no complete line yet (an
    empty transcript, or a live session whose first line is still being
    written) has no cursor row, so a plain UPDATE would match zero rows and
    `file_changed` would keep reporting it changed forever."""
    conn.execute(
        """INSERT INTO cursors(path, session_id, agent_id, byte_offset, mtime, size, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET
               mtime = excluded.mtime, size = excluded.size, updated_at = excluded.updated_at""",
        (key, session_id, agent_id, offset, stat[0], stat[1], now),
    )


def ingest_file(conn: sqlite3.Connection, path: Path, session_id: str, agent_id: str,
                *, now: float | None = None) -> int:
    """Ingest lines appended to ``path`` since its cursor. Returns lines read."""
    if now is None:
        now = time.time()
    offset = _cursor(conn, path)
    lines, new_offset, start_offset = _read_new_lines(path, offset)
    stat = _stat(path) or (0.0, 0)
    if not lines:
        _touch_cursor(conn, str(path), session_id, agent_id, offset, stat, now)
        return 0
    return _ingest_lines(conn, _local_origin(path, agent_id), session_id, agent_id,
                         lines, new_offset, start_offset, stat, now)


def _ingest_lines(conn: sqlite3.Connection, origin: _Origin, session_id: str, agent_id: str,
                  lines: list[str], new_offset: int, start_offset: int,
                  stat: tuple[float, int], now: float,
                  profile_of: ProfileOf | None = None) -> int:
    """Fold ``lines`` (read from ``origin`` starting at ``start_offset``) into
    the fact tables and advance the file's cursor. Where the bytes CAME from —
    a host file or a docker volume — is the caller's business; from here on it
    is one code path, which is what keeps the two sources agreeing."""
    facts = fold(lines, default_agent=agent_id,
                 initial_owner=_initial_owner(conn, session_id, agent_id, start_offset))
    if agent_id == MAIN_AGENT:
        _upsert_session_identity(conn, session_id, facts, origin, now, profile_of)
        # The LAST owner, so the next incremental batch can carry on from it.
        # Deliberately not `owner_account_uuid`, which is the first and write-once.
        if facts.bridge_owner_uuid:
            conn.execute(
                "UPDATE sessions SET bridge_owner_uuid = ? WHERE session_id = ?",
                (facts.bridge_owner_uuid, session_id),
            )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO sessions(session_id, updated_at) VALUES (?, ?)",
            (session_id, now),
        )
        # The agent row exists whether or not this batch saw its task: an
        # agent whose opening prompt was pruned must still be listable.
        # COALESCE, not a plain SET — an incremental sync reads only the TAIL,
        # where the opening prompt is not, so overwriting with the NULL it
        # just saw would erase the label on every subsequent sync. Same trap
        # that once shipped 3 qualifiers out of 1,265.
        conn.execute(
            """INSERT INTO agents(session_id, agent_id, task, description) VALUES (?,?,?,?)
               ON CONFLICT(session_id, agent_id) DO UPDATE SET
                   task = COALESCE(excluded.task, agents.task),
                   description = COALESCE(excluded.description, agents.description)""",
            (session_id, agent_id, facts.task, origin.description),
        )
    _write_facts(conn, session_id, facts, new_offset)
    conn.execute(
        "INSERT OR REPLACE INTO cursors(path, session_id, agent_id, byte_offset, mtime, size, "
        "updated_at) VALUES (?,?,?,?,?,?,?)",
        (origin.key, session_id, agent_id, new_offset, stat[0], stat[1], now),
    )
    if agent_id == MAIN_AGENT:
        conn.execute(
            "UPDATE sessions SET transcript_mtime = ? WHERE session_id = ?",
            (stat[0], session_id),
        )
    return len(lines)


def agent_description(transcript_path: Path) -> str | None:
    """The agent's short label, from `agent-<id>.meta.json` beside its transcript.

    Claude Code writes that file for all but a handful of agents (979 of 980 on
    the machine this was built for), and its `description` is a purpose-built
    three-to-five word summary — "Review balance package correctness". The
    `task` column, by contrast, holds the agent's opening PROMPT: 1,200 to 3,500
    characters, which as a name blows a table column apart and truncates into a
    mangled paragraph.

    None on any failure, and None for a main transcript, which has no meta file.
    Only `description` is read: the file also names the team, the colour and the
    permission mode, none of which is a label.
    """
    meta = transcript_path.with_suffix(".meta.json")
    if not meta.is_file():
        return None
    try:
        return description_from_meta(meta.read_text())
    except OSError:
        return None


def description_from_meta(text: str) -> str | None:
    """The ``description`` in an ``agent-<id>.meta.json``'s TEXT — the seam a
    docker volume's meta file goes through — or None on anything unusable."""
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError:
        return None
    value = data.get("description") if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def subagent_files(transcript_path: Path, session_id: str) -> list[tuple[Path, str]]:
    folder = transcript_path.parent / session_id / "subagents"
    if not folder.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for candidate in sorted(folder.glob("agent-*.jsonl")):
        match = _AGENT_FILE_RE.match(candidate.name)
        if match:
            out.append((candidate, match.group("agent")))
    return out


def _active_ms(conn: sqlite3.Connection, session_id: str) -> int:
    """Summed turn durations, each capped at the time elapsed since the turn
    began (the latest prompt from the same agent, or that agent's previous
    turn end).

    Claude Code occasionally writes a ``durationMs`` far longer than the
    session itself — observed after a multi-day resume — and an uncapped sum
    then exceeds the session's own span. A duration with no earlier prompt
    from its agent is not counted: there is nothing to measure it against.
    """
    total = 0
    prompted: dict[str, float] = {}
    for kind, agent_id, ts, value in conn.execute(
        """SELECT kind, agent_id, ts, value FROM events
           WHERE session_id = ? AND kind IN ('prompt', 'turn_duration') AND ts IS NOT NULL
           ORDER BY ts, kind = 'turn_duration'""",
        (session_id,),
    ):
        if kind == "prompt":
            prompted[agent_id] = ts
        elif agent_id in prompted:
            total += min(value or 0, round((ts - prompted[agent_id]) * 1000))
            # A later duration with no NEW prompt is capped from the end of
            # this turn, not re-measured from the same stale prompt.
            prompted[agent_id] = ts
    return total


def rollup(conn: sqlite3.Connection, session_id: str, *, now: float | None = None) -> None:
    """Recompute the denormalised session totals from the fact tables."""
    if now is None:
        now = time.time()
    totals = conn.execute(
        """SELECT COUNT(*) AS turns,
                  COALESCE(SUM(input_tokens), 0), COALESCE(SUM(cache_read_tokens), 0),
                  COALESCE(SUM(cache_creation_tokens), 0), COALESCE(SUM(output_tokens), 0),
                  COALESCE(SUM(thinking_tokens), 0), COALESCE(SUM(tool_calls), 0),
                  -- Agents that OWN a turn. A snapshot file whose every call is
                  -- a replay owned by a longer snapshot (see `scripts.replay`)
                  -- owns none and so is not counted: one resumed agent is one
                  -- subagent, not one per snapshot file it left behind.
                  COUNT(DISTINCT CASE WHEN agent_id <> '' THEN agent_id END)
           FROM turns WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    peak = conn.execute(
        """SELECT COALESCE(MAX(input_tokens + cache_read_tokens + cache_creation_tokens), 0)
           FROM turns WHERE session_id = ? AND agent_id = ''""",
        (session_id,),
    ).fetchone()[0]
    cold = conn.execute(
        """SELECT COUNT(*) FROM turns
           WHERE session_id = ? AND agent_id = '' AND cache_creation_tokens > cache_read_tokens""",
        (session_id,),
    ).fetchone()[0]
    # A publish whose url already appeared earlier in this session is a
    # redeploy of the same page (the call names the url only when updating
    # an artifact from ANOTHER session; same-session republishes reuse the
    # file path and carry no url). Distinct pages, not publishes, are what
    # "how many artifacts" means.
    conn.execute(
        """UPDATE artifacts SET redeploy = 1
           WHERE session_id = ? AND url IS NOT NULL AND EXISTS (
               SELECT 1 FROM artifacts b
               WHERE b.session_id = artifacts.session_id AND b.url = artifacts.url
                 AND (b.ts < artifacts.ts OR (b.ts = artifacts.ts AND b.rowid < artifacts.rowid)))""",
        (session_id,),
    )
    artifacts = conn.execute(
        "SELECT COUNT(DISTINCT COALESCE(url, tool_use_id)) FROM artifacts WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    churn = conn.execute(
        """SELECT COALESCE(SUM(lines_added), 0), COALESCE(SUM(lines_removed), 0),
                  COUNT(DISTINCT file_path)
           FROM file_edits WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    prompts = conn.execute(
        "SELECT COUNT(*) FROM events WHERE session_id = ? AND kind = 'prompt' AND agent_id = ''",
        (session_id,),
    ).fetchone()[0]
    compactions = conn.execute(
        "SELECT COUNT(*) FROM events WHERE session_id = ? AND kind = 'compaction'",
        (session_id,),
    ).fetchone()[0]
    active_ms = _active_ms(conn, session_id)
    models = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT model FROM turns WHERE session_id = ? AND model IS NOT NULL "
            "ORDER BY model",
            (session_id,),
        )
    ]
    transcript = conn.execute(
        "SELECT transcript_path FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    size = 0
    if transcript and transcript[0]:
        if store.is_volume_label(transcript[0]):
            # Not a host path: the size is what the volume's listing said when
            # the cursor last saw it. `getsize` on it would stat some relative
            # "docker:/..." path under whatever the cwd happens to be.
            row = conn.execute(
                "SELECT size FROM cursors WHERE path = ?", (transcript[0],)).fetchone()
            size = int(row[0]) if row else 0
        else:
            try:
                size = os.path.getsize(transcript[0])
            except OSError:
                size = 0
    conn.execute(
        """UPDATE sessions SET turns=?, input_tokens=?, cache_read_tokens=?, cache_creation_tokens=?,
               output_tokens=?, thinking_tokens=?, tool_calls=?, subagents=?, peak_context_tokens=?,
               cold_turns=?, artifacts=?, prompts=?, compactions=?, active_ms=?, models=?,
               lines_added=?, lines_removed=?, files_touched=?,
               transcript_bytes=?, updated_at=?
           WHERE session_id = ?""",
        (*totals, peak, cold, artifacts, prompts, compactions, active_ms, json.dumps(models),
         int(churn[0]), int(churn[1]), int(churn[2]),
         size, now, session_id),
    )
    # Copied records are skipped by `_write_facts`, but `_upsert_session_identity`
    # already stamped `started_at` from the raw (unfiltered) transcript, so a
    # resumed session would show as starting when its PARENT did. The main
    # agent's own owned records are the truth when it has any; with none (a
    # copy this session never actually owned) the earlier stamp stands.
    conn.execute(
        """UPDATE sessions SET started_at = COALESCE(
               (SELECT MIN(ts) FROM (SELECT ts FROM turns WHERE session_id = ?1 AND agent_id = ''
                                     UNION ALL
                                     SELECT ts FROM events WHERE session_id = ?1 AND agent_id = '')),
               started_at)
           WHERE session_id = ?1""",
        (session_id,),
    )


def ingest_session(conn: sqlite3.Connection, transcript_path: Path, session_id: str | None = None,
                   *, now: float | None = None) -> dict[str, int]:
    """Ingest a session's main transcript plus any subagent transcripts, then
    roll the session up. Returns ``{"lines": n, "files": m}``."""
    if now is None:
        now = time.time()
    sid = session_id or transcript_path.stem
    lines = ingest_file(conn, transcript_path, sid, MAIN_AGENT, now=now)
    files = 1
    for path, agent_id in subagent_files(transcript_path, sid):
        lines += ingest_file(conn, path, sid, agent_id, now=now)
        files += 1
    exists = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (sid,)).fetchone()
    if exists:
        rollup(conn, sid, now=now)
    conn.commit()
    return {"lines": lines, "files": files}


def scan_transcripts(projects: Path) -> list[Path]:
    """Every main transcript ``<slug>/<session>.jsonl`` under ``projects``
    (subagent files live one level deeper and are reached via their session)."""
    if not projects.is_dir():
        return []
    out: list[Path] = []
    for slug_dir in sorted(p for p in projects.iterdir() if p.is_dir()):
        out.extend(sorted(slug_dir.glob("*.jsonl")))
    return out


# Most bytes one helper-container read is asked for. A first sync of a big
# volume is a lot of history; reading it in one call would hold all of it in
# memory and give the dashboard's 120s ceiling nothing to show for a kill.
# Batched, each batch is committed as it lands, so progress survives either.
_VOLUME_BATCH_BYTES = 64 * 1024 * 1024
# Wall-clock a sync spends on volumes before it stops starting new batches and
# reports `partial`. Under the dashboard's 120s subprocess ceiling, so a large
# first backfill finishes over a few polls instead of being killed mid-flight.
VOLUME_BUDGET_SECONDS = 80.0
# How often a volume with sessions still lacking an account is asked who is
# logged in. An API-key volume never gets one, and re-asking on every
# once-a-minute poll would start a container each time for nothing.
_ACCOUNT_PROBE_INTERVAL_SECONDS = 3600.0


def _cursor_row(conn: sqlite3.Connection, key: str) -> tuple[int, float, int] | None:
    row = conn.execute(
        "SELECT byte_offset, mtime, size FROM cursors WHERE path = ?", (key,)).fetchone()
    return (int(row[0]), float(row[1]), int(row[2])) if row else None


def _volume_moves(conn: sqlite3.Connection, source: VolumeSource,
                  session: RemoteSession) -> dict[str, tuple[Any, int]]:
    """``{relpath: (file, offset to read from)}`` for the session's files that
    moved since their cursor last saw them (a never-seen file has no cursor and
    counts as moved). Same test as `file_changed`, over the listing's
    mtime/size instead of a stat. The offset is the cursor's when the file
    only GREW; one that shrank (rewritten) restarts from 0."""
    moves: dict[str, tuple[Any, int]] = {}
    for file in session.files:
        row = _cursor_row(conn, source.key(file.relpath))
        if row is None:
            moves[file.relpath] = (file, 0)
        elif (row[1], row[2]) != (file.mtime, file.size):
            moves[file.relpath] = (file, row[0] if row[0] <= file.size else 0)
    return moves


def _ingest_volume_session(conn: sqlite3.Connection, source: VolumeSource, session: RemoteSession,
                           moves: Mapping[str, tuple[Any, int]], chunks: Mapping[str, bytes],
                           *, now: float, profile_of: ProfileOf) -> int:
    """Ingest the moved files of one volume session from the bytes already
    read, then roll it up — `ingest_session`'s counterpart. Returns lines."""
    total = 0
    ordered = [(session.main, MAIN_AGENT), *((f, agent) for agent, f in session.subagents)]
    for file, agent_id in ordered:
        if file.relpath not in moves:
            continue
        offset = moves[file.relpath][1]
        key = source.key(file.relpath)
        stat = (file.mtime, file.size)
        if offset >= file.size:
            chunk = b""                    # only the mtime moved: nothing to read
        else:
            got = chunks.get(file.relpath)
            if got is None:
                continue                   # vanished between the listing and the read
            chunk = got
        lines, new_offset = _complete_lines(chunk, offset)
        if not lines:
            _touch_cursor(conn, key, session.session_id, agent_id, offset, stat, now)
            continue
        description = None
        if agent_id != MAIN_AGENT:
            meta = chunks.get(file.meta_relpath)
            description = description_from_meta(meta.decode(errors="replace")) if meta else None
        origin = _Origin(key=key, slug=session.slug, config_dir=source.label,
                         description=description)
        total += _ingest_lines(conn, origin, session.session_id, agent_id, lines, new_offset,
                               offset, stat, now, profile_of)
    if conn.execute("SELECT 1 FROM sessions WHERE session_id = ?",
                    (session.session_id,)).fetchone():
        rollup(conn, session.session_id, now=now)
    conn.commit()
    return total


def sync_volume(conn: sqlite3.Connection, source: VolumeSource, *, now: float,
                profile_of: ProfileOf, deadline: float | None = None) -> dict[str, Any]:
    """Reconcile the store against one Docker volume, read in place.

    One helper call lists every transcript; sessions with no file that moved
    are skipped on the listing alone, so a sync with nothing new is that one
    call. For those that did move, only the moved files' NEW bytes are read
    (plus each moved subagent's tiny meta file), in size-capped batches, each
    ingested and committed before the next is read.

    ``deadline`` (a `time.monotonic()` value) is checked between batches, never
    before the first: some progress is always made. Past it, the rest waits for
    the next sync and the result says ``partial``. A failed LISTING raises
    `VolumeError` (nothing was done); a failed READ part-way is returned as
    ``error`` beside the counts of what earlier batches did commit. `sync`
    records either and moves on.
    """
    sessions = group_sessions(source.list_files())
    result: dict[str, Any] = {
        "name": source.name, "scanned": sum(len(s.files) for s in sessions),
        "changed": 0, "lines": 0,
    }
    pending = [(s, moves) for s in sessions if (moves := _volume_moves(conn, source, s))]
    changed: list[str] = []
    batch: list[tuple[RemoteSession, dict[str, tuple[Any, int]]]] = []
    batch_bytes = 0

    def flush() -> None:
        nonlocal batch, batch_bytes
        requests: list[tuple[str, int]] = []
        for session, moves in batch:
            for relpath, (file, offset) in moves.items():
                if offset < file.size:
                    requests.append((relpath, offset))
                if relpath != session.main.relpath:
                    requests.append((file.meta_relpath, 0))
        chunks = source.read(requests)
        for session, moves in batch:
            result["lines"] += _ingest_volume_session(
                conn, source, session, moves, chunks, now=now, profile_of=profile_of)
            changed.append(session.session_id)
        batch, batch_bytes = [], 0

    try:
        for index, (session, moves) in enumerate(pending):
            if batch and batch_bytes >= _VOLUME_BATCH_BYTES:
                flush()
                if deadline is not None and time.monotonic() > deadline:
                    result["partial"] = True
                    result["remaining"] = len(pending) - index
                    break
            batch.append((session, moves))
            batch_bytes += sum(max(file.size - offset, 0) for file, offset in moves.values())
        if batch:       # empty exactly when the loop broke out on the deadline
            flush()
    except VolumeError as exc:
        # A read failed part-way. What earlier batches committed stays, and is
        # counted: the caller still needs to know those sessions changed.
        result["error"] = str(exc)
    result["changed"] = len(changed)
    result["sessions"] = changed
    return result


def sync(conn: sqlite3.Connection, projects: Path | list[Path], *, now: float | None = None,
         full: bool = False, volumes: Sequence[VolumeSource] = (),
         volume_budget: float | None = VOLUME_BUDGET_SECONDS) -> dict[str, Any]:
    """Pull-on-demand reconciliation of the store against the transcripts on
    disk: stat every transcript (and its subagent files), ingest the tail of
    each one whose mtime/size moved since the cursor last saw it, and record
    the sync time. Idempotent; a sync with nothing changed is a directory
    walk and no reads.

    ``projects`` is one ``projects/`` dir or several (one per watched Claude
    config dir — see ``store.projects_dirs``); every transcript under each is
    folded into the one store, its session row recording its ``config_dir``.

    ``full`` forgets every cursor first, so every file is re-read from byte 0
    — the way to populate columns added by a schema migration for turns that
    were ingested before it. Safe because every write is idempotent.

    ``volumes`` are Docker volumes read in place after the local dirs (see
    `sync_volume`). Docker trouble NEVER raises out of here: a volume that
    cannot be read is skipped and named in ``volume_errors``, and the local
    dirs above it have already synced.

    Returns ``{"scanned", "changed", "lines", "sessions": [ids...], "synced_at",
    "volumes": [per-volume counts], "volume_errors": [{"volume", "error"}]}``
    — the totals span local dirs and volumes alike.
    """
    if now is None:
        now = time.time()
    started = time.monotonic()
    if full:
        conn.execute("DELETE FROM cursors")
    roots = [projects] if isinstance(projects, Path) else list(projects)
    scanned = 0
    lines = 0
    changed: list[str] = []
    for transcript in (t for root in roots for t in scan_transcripts(root)):
        sid = transcript.stem
        files = [transcript, *(path for path, _ in subagent_files(transcript, sid))]
        scanned += len(files)
        if not any(file_changed(conn, path) for path in files):
            continue
        result = ingest_session(conn, transcript, sid, now=now)
        lines += result["lines"]
        changed.append(sid)
    resolver = ProfileResolver(volumes)
    volume_results: list[dict[str, Any]] = []
    volume_errors: list[dict[str, str]] = []
    deadline = None if volume_budget is None else started + volume_budget
    for source in volumes:
        try:
            outcome = sync_volume(conn, source, now=now, profile_of=resolver, deadline=deadline)
        except VolumeError as exc:
            resolver.disable(source.label)
            volume_errors.append({"volume": source.name, "error": str(exc)})
            continue
        if "error" in outcome:
            resolver.disable(source.label)
            volume_errors.append({"volume": source.name, "error": outcome.pop("error")})
        scanned += outcome["scanned"]
        lines += outcome["lines"]
        changed.extend(outcome.pop("sessions"))
        volume_results.append(outcome)
    # One-time: fill `config_dir` on rows from before the column existed. Every
    # row ingested since carries it, so once the sweep has run there is
    # nothing left for it to find — the flag spares every later sync the scan.
    if conn.execute("SELECT 1 FROM meta WHERE key = 'config_dirs_backfilled'").fetchone() is None:
        backfill_config_dirs(conn)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('config_dirs_backfilled', '1')")
    # Not one-time-flagged, unlike the sweep above — see `backfill_account_uuids`.
    backfill_account_uuids(conn, now=now, profile_of=resolver)
    for label in resolver.read:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                     (_PROBE_KEY + label, str(now)))
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('synced_at', ?)", (str(now),)
    )
    conn.commit()
    return {
        "scanned": scanned,
        "changed": len(changed),
        "lines": lines,
        "sessions": changed,
        "synced_at": now,
        "volumes": volume_results,
        "volume_errors": volume_errors,
    }


_PROBE_KEY = "account_probe:"


def _probe_due(conn: sqlite3.Connection, resolver: ProfileResolver, label: str,
               now: float) -> bool:
    """Whether a volume's account should be (re)read to backfill its sessions:
    yes if a helper already read it this sync (free), or if it has not been
    asked within `_ACCOUNT_PROBE_INTERVAL_SECONDS`; never for a label no
    configured volume owns."""
    if not resolver.knows(label):
        return False
    if resolver.probed(label):
        return True
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (_PROBE_KEY + label,)).fetchone()
    return row is None or now - float(row[0]) >= _ACCOUNT_PROBE_INTERVAL_SECONDS


def backfill_account_uuids(conn: sqlite3.Connection, *, now: float | None = None,
                           profile_of: ProfileResolver | None = None) -> int:
    """Fill ``sessions.account_uuid`` for rows that have none yet, from the
    CURRENT login of the config dir each was ingested from — the same shape
    of sweep ``backfill_config_dirs`` runs for the column beside it, so a
    session ingested before this feature shipped (or one whose config dir was
    logged out the first time it ran) is not stuck NULL forever.

    Unlike ``backfill_config_dirs`` this is NOT one-time-flagged: its source —
    whether a config dir is currently logged in, and as whom — can become true
    only later (someone logs in after weeks of API-key use), so every sync
    re-checks whatever is still NULL. Cheap either way: the query only ever
    touches rows with no account, and a config dir's profile is read at most
    once per call regardless of how many of its sessions are pending.

    Still write-once in effect: a row this fills never has NULL again, so a
    later run of this same sweep leaves it untouched — the account a session
    picks up here is the one it keeps.

    A ``docker://`` config dir is asked through ``profile_of`` (a container
    start per read), so it is rate-limited — see `_probe_due`.
    """
    if now is None:
        now = time.time()
    resolver = profile_of or ProfileResolver()
    rows = conn.execute(
        "SELECT session_id, config_dir FROM sessions "
        "WHERE account_uuid IS NULL AND config_dir IS NOT NULL"
    ).fetchall()
    profiles: dict[str, str | None] = {}
    filled = 0
    for session_id, config_dir in rows:
        if config_dir not in profiles:
            if store.is_volume_label(config_dir) and not _probe_due(conn, resolver, config_dir, now):
                profiles[config_dir] = None
            else:
                _, profiles[config_dir] = _account_snapshot(conn, config_dir, now, resolver)
        account_uuid = profiles[config_dir]
        if account_uuid is None:
            continue
        conn.execute(
            "UPDATE sessions SET account_uuid = ? WHERE session_id = ?",
            (account_uuid, session_id),
        )
        filled += 1
    return filled


def backfill_config_dirs(conn: sqlite3.Connection) -> int:
    """Fill ``sessions.config_dir`` for rows ingested before the column
    existed, from the transcript path they already carry — so an existing
    store reads correctly the first sync after upgrading, without a
    ``--full`` re-read. Returns the number of rows filled."""
    rows = conn.execute(
        "SELECT session_id, transcript_path FROM sessions "
        "WHERE config_dir IS NULL AND transcript_path IS NOT NULL"
    ).fetchall()
    filled = 0
    for session_id, transcript_path in rows:
        if store.is_volume_label(transcript_path):
            continue      # not a host path; volume rows are stamped at ingest
        config_dir = config_dir_of(Path(transcript_path))
        if config_dir is None:
            continue
        conn.execute(
            "UPDATE sessions SET config_dir = ? WHERE session_id = ?", (config_dir, session_id)
        )
        filled += 1
    return filled


def backfill(conn: sqlite3.Connection, projects: Path, *, now: float | None = None) -> dict[str, Any]:
    """First-run alias of :func:`sync` — every transcript is "changed" to an
    empty store, so the two are the same operation."""
    return sync(conn, projects, now=now)
