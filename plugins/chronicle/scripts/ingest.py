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
from pathlib import Path
from typing import Any

from scripts.transcript import MAIN_AGENT, Facts, fold

_GIT_TIMEOUT_SECONDS = 2
_AGENT_FILE_RE = re.compile(r"^agent-(?P<agent>[^.]+)\.jsonl$")


def repo_root_of(cwd: str | None) -> str | None:
    """The MAIN repo root ``cwd`` belongs to (worktrees resolve to their
    primary checkout via the shared git common dir), or None outside git /
    on any failure. Bounded so a stalled git never stalls a hook."""
    if not cwd or not os.path.isdir(cwd):
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


def _read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Lines appended after ``offset``, and the new offset (after the last
    complete line). A file that shrank (rewritten) restarts from 0."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset
    if offset > size:
        offset = 0
    if offset == size:
        return [], offset
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], offset
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return [], offset
    complete = chunk[: last_nl + 1]
    return complete.decode("utf-8", errors="replace").splitlines(), offset + len(complete)


def _cursor(conn: sqlite3.Connection, path: Path) -> int:
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


def _write_facts(conn: sqlite3.Connection, session_id: str, facts: Facts) -> None:
    # tool_calls rows first: a message split across two ingests (a Stop hook
    # or a dashboard Sync landing mid-write) folds into two DISJOINT Turn
    # objects, one per call, each seeing only the tool_use blocks that were
    # on disk at the time — so len(t.tool_uses) is only THIS batch's count,
    # not the message's total. tool_calls rows are keyed by tool_use_id and
    # never overwritten (INSERT OR IGNORE), so they accumulate correctly
    # across ingests; turns.tool_calls below is then a COUNT(*) against that
    # already-correct table, not the batch-local len().
    conn.executemany(
        """INSERT OR IGNORE INTO tool_calls(session_id, tool_use_id, agent_id, message_id,
               tool_name, ts) VALUES (?,?,?,?,?,?)""",
        [
            (session_id, tool_id, t.agent_id, t.message_id, name, t.ts)
            for t in facts.turns.values()
            for tool_id, name in t.tool_uses
        ],
    )
    conn.executemany(
        """INSERT INTO turns(session_id, agent_id, message_id, request_id, ts, model,
               input_tokens, cache_read_tokens, cache_creation_tokens, output_tokens,
               thinking_tokens, cache_5m_tokens, cache_1h_tokens, tool_calls, stop_reason, effort)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,
               (SELECT COUNT(*) FROM tool_calls
                WHERE session_id = ? AND agent_id = ? AND message_id = ?),
               ?,?)
           ON CONFLICT(session_id, agent_id, message_id) DO UPDATE SET
               request_id = excluded.request_id, ts = excluded.ts, model = excluded.model,
               input_tokens = excluded.input_tokens, cache_read_tokens = excluded.cache_read_tokens,
               cache_creation_tokens = excluded.cache_creation_tokens,
               output_tokens = excluded.output_tokens, thinking_tokens = excluded.thinking_tokens,
               cache_5m_tokens = excluded.cache_5m_tokens, cache_1h_tokens = excluded.cache_1h_tokens,
               tool_calls = excluded.tool_calls, stop_reason = excluded.stop_reason,
               effort = excluded.effort""",
        [
            (session_id, t.agent_id, t.message_id, t.request_id, t.ts, t.model,
             t.input_tokens, t.cache_read_tokens, t.cache_creation_tokens, t.output_tokens,
             t.thinking_tokens, t.cache_5m_tokens, t.cache_1h_tokens,
             session_id, t.agent_id, t.message_id,
             t.stop_reason, t.effort)
            for t in facts.turns.values()
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO events(session_id, uuid, agent_id, kind, ts, value) "
        "VALUES (?,?,?,?,?,?)",
        [(session_id, e.uuid, e.agent_id, e.kind, e.ts, e.value) for e in facts.events],
    )
    # Results may land in a later ingest than their call (a Stop hook fires
    # between the two), so this is an UPDATE against whatever row exists.
    conn.executemany(
        "UPDATE tool_calls SET result_chars = ?, result_ts = ? "
        "WHERE session_id = ? AND tool_use_id = ?",
        [(r.chars, r.ts, session_id, r.tool_use_id) for r in facts.results.values()],
    )
    conn.executemany(
        """INSERT OR REPLACE INTO artifacts(session_id, tool_use_id, agent_id, ts, url, title,
               description, favicon, redeploy) VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (session_id, a.tool_use_id, t.agent_id, t.ts, a.url, a.title, a.description,
             a.favicon, int(a.redeploy))
            for t in facts.turns.values()
            for a in t.artifacts.values()
        ],
    )
    # An artifact whose result landed in THIS ingest but whose call was
    # written by an earlier one (a Stop hook fired between them): fill the
    # url on the existing row.
    conn.executemany(
        "UPDATE artifacts SET url = ? WHERE session_id = ? AND tool_use_id = ? AND url IS NULL",
        [(r.artifact_url, session_id, r.tool_use_id)
         for r in facts.results.values() if r.artifact_url],
    )


def _upsert_session_identity(conn: sqlite3.Connection, session_id: str, facts: Facts,
                             transcript_path: Path, now: float) -> None:
    """Create the session row if absent, then fill identity columns from the
    facts without clobbering a known value with None."""
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, updated_at) VALUES (?, ?)",
        (session_id, now),
    )
    cwd = facts.cwd
    updates: dict[str, Any] = {
        "project_slug": project_slug_of(transcript_path),
        "transcript_path": str(transcript_path),
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


def ingest_file(conn: sqlite3.Connection, path: Path, session_id: str, agent_id: str,
                *, now: float | None = None) -> int:
    """Ingest lines appended to ``path`` since its cursor. Returns lines read."""
    if now is None:
        now = time.time()
    offset = _cursor(conn, path)
    lines, new_offset = _read_new_lines(path, offset)
    stat = _stat(path) or (0.0, 0)
    if not lines:
        # Nothing new to parse, but remember the file as seen so a later
        # sync does not re-stat it as "changed" (e.g. a touched-but-empty
        # tail). An upsert, not a bare UPDATE: a file seen for the first
        # time with no complete line yet (an empty transcript, or a live
        # session whose first line is still being written) has no cursor
        # row, so a plain UPDATE would match zero rows and file_changed
        # would keep reporting it changed forever.
        conn.execute(
            """INSERT INTO cursors(path, session_id, agent_id, byte_offset, mtime, size, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                   mtime = excluded.mtime, size = excluded.size, updated_at = excluded.updated_at""",
            (str(path), session_id, agent_id, offset, stat[0], stat[1], now),
        )
        return 0
    facts = fold(lines, default_agent=agent_id)
    if agent_id == MAIN_AGENT:
        _upsert_session_identity(conn, session_id, facts, path, now)
    else:
        conn.execute(
            "INSERT OR IGNORE INTO sessions(session_id, updated_at) VALUES (?, ?)",
            (session_id, now),
        )
    _write_facts(conn, session_id, facts)
    conn.execute(
        "INSERT OR REPLACE INTO cursors(path, session_id, agent_id, byte_offset, mtime, size, "
        "updated_at) VALUES (?,?,?,?,?,?,?)",
        (str(path), session_id, agent_id, new_offset, stat[0], stat[1], now),
    )
    if agent_id == MAIN_AGENT:
        conn.execute(
            "UPDATE sessions SET transcript_mtime = ? WHERE session_id = ?",
            (stat[0], session_id),
        )
    return len(lines)


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


def rollup(conn: sqlite3.Connection, session_id: str, *, now: float | None = None) -> None:
    """Recompute the denormalised session totals from the fact tables."""
    if now is None:
        now = time.time()
    totals = conn.execute(
        """SELECT COUNT(*) AS turns,
                  COALESCE(SUM(input_tokens), 0), COALESCE(SUM(cache_read_tokens), 0),
                  COALESCE(SUM(cache_creation_tokens), 0), COALESCE(SUM(output_tokens), 0),
                  COALESCE(SUM(thinking_tokens), 0), COALESCE(SUM(tool_calls), 0),
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
    prompts = conn.execute(
        "SELECT COUNT(*) FROM events WHERE session_id = ? AND kind = 'prompt' AND agent_id = ''",
        (session_id,),
    ).fetchone()[0]
    compactions = conn.execute(
        "SELECT COUNT(*) FROM events WHERE session_id = ? AND kind = 'compaction'",
        (session_id,),
    ).fetchone()[0]
    active_ms = conn.execute(
        "SELECT COALESCE(SUM(value), 0) FROM events WHERE session_id = ? AND kind = 'turn_duration'",
        (session_id,),
    ).fetchone()[0]
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
        try:
            size = os.path.getsize(transcript[0])
        except OSError:
            size = 0
    conn.execute(
        """UPDATE sessions SET turns=?, input_tokens=?, cache_read_tokens=?, cache_creation_tokens=?,
               output_tokens=?, thinking_tokens=?, tool_calls=?, subagents=?, peak_context_tokens=?,
               cold_turns=?, artifacts=?, prompts=?, compactions=?, active_ms=?, models=?,
               transcript_bytes=?, updated_at=?
           WHERE session_id = ?""",
        (*totals, peak, cold, artifacts, prompts, compactions, active_ms, json.dumps(models),
         size, now, session_id),
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


def mark_started(conn: sqlite3.Connection, session_id: str, *, cwd: str | None,
                 transcript_path: str | None, now: float | None = None) -> None:
    if now is None:
        now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, updated_at, started_at) VALUES (?, ?, ?)",
        (session_id, now, now),
    )
    if cwd:
        conn.execute(
            "UPDATE sessions SET cwd = ?, repo_root = COALESCE(?, repo_root) WHERE session_id = ?",
            (cwd, repo_root_of(cwd), session_id),
        )
    if transcript_path:
        conn.execute(
            "UPDATE sessions SET transcript_path = ?, project_slug = ? WHERE session_id = ?",
            (transcript_path, Path(transcript_path).parent.name, session_id),
        )
    # A resumed session gets a fresh SessionStart: never clear a recorded end
    # time here silently — reopen instead so the row reads as live again.
    conn.execute(
        "UPDATE sessions SET ended_at = NULL, end_reason = NULL, updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()


def mark_ended(conn: sqlite3.Connection, session_id: str, *, reason: str | None,
               now: float | None = None) -> None:
    if now is None:
        now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, updated_at) VALUES (?, ?)", (session_id, now)
    )
    conn.execute(
        "UPDATE sessions SET ended_at = ?, end_reason = ?, updated_at = ? WHERE session_id = ?",
        (now, reason, now, session_id),
    )
    conn.commit()


def scan_transcripts(projects: Path) -> list[Path]:
    """Every main transcript ``<slug>/<session>.jsonl`` under ``projects``
    (subagent files live one level deeper and are reached via their session)."""
    if not projects.is_dir():
        return []
    out: list[Path] = []
    for slug_dir in sorted(p for p in projects.iterdir() if p.is_dir()):
        out.extend(sorted(slug_dir.glob("*.jsonl")))
    return out


def sync(conn: sqlite3.Connection, projects: Path, *, now: float | None = None,
         full: bool = False) -> dict[str, Any]:
    """Pull-on-demand reconciliation of the store against the transcripts on
    disk: stat every transcript (and its subagent files), ingest the tail of
    each one whose mtime/size moved since the cursor last saw it, and record
    the sync time. Idempotent; a sync with nothing changed is a directory
    walk and no reads.

    ``full`` forgets every cursor first, so every file is re-read from byte 0
    — the way to populate columns added by a schema migration for turns that
    were ingested before it. Safe because every write is idempotent.

    Returns ``{"scanned", "changed", "lines", "sessions": [ids...], "synced_at"}``.
    """
    if now is None:
        now = time.time()
    if full:
        conn.execute("DELETE FROM cursors")
    scanned = 0
    lines = 0
    changed: list[str] = []
    for transcript in scan_transcripts(projects):
        sid = transcript.stem
        files = [transcript, *(path for path, _ in subagent_files(transcript, sid))]
        scanned += len(files)
        if not any(file_changed(conn, path) for path in files):
            continue
        result = ingest_session(conn, transcript, sid, now=now)
        lines += result["lines"]
        changed.append(sid)
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
    }


def backfill(conn: sqlite3.Connection, projects: Path, *, now: float | None = None) -> dict[str, Any]:
    """First-run alias of :func:`sync` — every transcript is "changed" to an
    empty store, so the two are the same operation."""
    return sync(conn, projects, now=now)
