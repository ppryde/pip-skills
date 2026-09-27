"""Shared fixture + snapshot helpers for the redaction round-trip tests
(``test_redact.py``): build one realistic-shaped transcript tree (a title, a
qualified Skill call, a file edit, a published Artifact, a rate-limit banner,
tool results carrying fake production data, and a subagent with its own task
line), ingest it, and reduce the resulting store to the handful of columns
the tests compare. Not itself a test file — nothing here is collected.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scripts import ingest, pricerefresh, report, store

from .conftest import TranscriptBuilder

# The one string that must never survive minimal/attribution redaction. Also
# planted (via the title and the subagent's task) where `titles` fidelity
# explicitly documents it can leak.
SECRET = "SECRET7f3c"

SESSION = "s1"
SLUG = "-repo"
T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:01:00.000Z"
T2 = "2026-09-01T10:02:00.000Z"


def write_remote_tree(root: Path) -> Path:
    """``<root>/projects/...`` + ``<root>/.claude.json``, shaped like a real
    remote box's Claude config dir. Returns ``root``."""
    projects = root / "projects"
    b = TranscriptBuilder(projects, SLUG, SESSION)
    b.raw({"type": "ai-title", "sessionId": SESSION, "aiTitle": f"Fix the {SECRET} bug"})
    b.prompt("u1", T0, f"Investigate the {SECRET} outage in payments (someone@example.com, Acme)")
    b.turn("m1", T0, tools=[("Skill", {"skill": "tribunal:reckoning"}), "Read"],
           effort="high", attributionSkill="tribunal:reckoning", attributionPlugin="tribunal")
    b.tool_result(
        "r1", T0, tool_use_id="m1-tool1",
        content=f"psql answer: {SECRET} hmm loaded old payments row for Acme, someone@example.com",
    )
    b.turn("m2", T1, tools=["Edit"])
    # The diff CONTENT is a sentinel that must never leave the box; only its
    # path and +/- line counts are redaction-safe.
    b.raw({
        "type": "user", "uuid": "e1", "sessionId": SESSION, "timestamp": T1,
        "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "m2-tool0", "content": "edited ok"}]},
        "toolUseResult": {"filePath": "/repo/app.py",
                          "structuredPatch": [{"lines": ["+x"] * 4 + ["-y"] * 2}]},
    })
    # An Artifact publish: title/description are prose (kept only at
    # `titles`); file_path + the published url are the redaction-safe rest.
    b.raw({
        "type": "assistant", "uuid": "a1", "sessionId": SESSION, "timestamp": T1,
        "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
        "message": {
            "id": "m3", "model": "claude-opus-5", "role": "assistant", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "m3-tool0", "name": "Artifact",
                        "input": {"file_path": "/tmp/report.html", "action": "publish",
                                  "title": f"T {SECRET} dashboard",
                                  "description": f"D {SECRET} customer view", "favicon": "chart"}}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    })
    b.raw({
        "type": "user", "uuid": "a1r", "sessionId": SESSION, "timestamp": T1,
        "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "m3-tool0",
             "content": "Published: https://claude.ai/code/artifact/abc123"}]},
    })
    b.limit_hit("L1", T2, "You've hit your weekly limit · resets Aug 16 at 8pm (Europe/London)")
    b.subagent("ag1", ["s1a"], T2, task=f"Look into {SECRET} for the customer, answer with root cause")
    b.write()
    account = {"oauthAccount": {"accountUuid": "acc-1", "organizationUuid": "org-1",
                                "emailAddress": "person@example.com", "fullName": "A Person"}}
    (root / ".claude.json").write_text(json.dumps(account))
    return root


def ingest_into(projects: Path, db_path: Path) -> sqlite3.Connection:
    """A fresh store at ``db_path``, fully synced from ``projects`` (with
    built-in prices seeded, so cost is computable without the network)."""
    conn = store.connect(db_path)
    pricerefresh.seed(conn)
    ingest.sync(conn, projects)
    return conn


def _rows(conn: sqlite3.Connection, sql: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(sql)]


def snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    """The columns the redaction tests compare, reduced to plain tuples so
    two stores (built from the same fixture at different fidelities) can be
    compared with ``==``."""
    return {
        "sessions": _rows(conn, "SELECT session_id, cwd, git_branch FROM sessions ORDER BY session_id"),
        "turns": _rows(conn, """SELECT session_id, agent_id, message_id, model, input_tokens,
            cache_read_tokens, cache_creation_tokens, output_tokens, thinking_tokens, tool_calls,
            stop_reason FROM turns ORDER BY session_id, agent_id, message_id"""),
        "tool_calls": _rows(conn, """SELECT session_id, tool_use_id, agent_id, tool_name
            FROM tool_calls ORDER BY session_id, tool_use_id"""),
        "events": _rows(conn, "SELECT session_id, uuid, kind, value FROM events ORDER BY session_id, uuid"),
        "attribution": _rows(conn, """SELECT session_id, agent_id, message_id, effort, skill, plugin,
            agent_type, mcp_server, mcp_tool FROM turns ORDER BY session_id, agent_id, message_id"""),
        "qualifiers": _rows(conn, "SELECT tool_use_id, qualifier FROM tool_calls ORDER BY tool_use_id"),
        "result_chars": _rows(conn, """SELECT tool_use_id, result_chars, tool_name
            FROM tool_calls ORDER BY tool_use_id"""),
        "file_edits": _rows(conn, """SELECT session_id, file_path, lines_added, lines_removed
            FROM file_edits ORDER BY session_id, tool_use_id"""),
        "artifacts": _rows(conn, """SELECT session_id, tool_use_id, url, favicon, redeploy
            FROM artifacts ORDER BY session_id, tool_use_id"""),
        "artifact_text": _rows(conn, "SELECT tool_use_id, title, description FROM artifacts ORDER BY tool_use_id"),
        "limit_hits": _rows(conn, """SELECT session_id, uuid, kind, model, resets_at
            FROM limit_hits ORDER BY session_id, uuid"""),
        "churn": _rows(conn, """SELECT s.session_id, s.lines_added, s.lines_removed, s.files_touched,
            (SELECT COUNT(*) FROM file_edits fe WHERE fe.session_id = s.session_id) AS edits
            FROM sessions s ORDER BY s.session_id"""),
        "titles": _rows(conn, "SELECT session_id, title FROM sessions ORDER BY session_id"),
        "agents": _rows(conn, "SELECT session_id, agent_id, task, description FROM agents ORDER BY session_id, agent_id"),
        "cost": [(r["session_id"], r["cost_usd"]) for r in report.sessions(conn)],
    }
