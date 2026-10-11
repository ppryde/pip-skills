"""Regenerated read-only file views of board.db state (WF-265 OL-10).

Sprints, knowledge facts and pending facts live in ``board.db``. The older
file trees -- ``sprints/<id>.md``, ``knowledge/facts|retired/*.md``,
``knowledge/knowledge.md``, ``knowledge/pending.jsonl`` -- are rewritten from
the tables after each write so that people, git, grep and an older plugin
version still find sensible files. Nothing reads them back except
``migrate.reimport_newer_files``, which treats a file modified AFTER the last
export as a write by an older plugin and imports it.

Best effort: a failed export is a stderr warning, never a failed verb. A file
whose content already matches is left alone (its mtime stays put).
``views_exported_at`` (meta) is stamped AFTER the files are written, so every
file this module wrote has an mtime at or before it.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import sqlite3

from scripts import knowledge as kb
from scripts import sprints as sp
from scripts.knowledge import ensure_kb, fact_filename, generate_knowledge_index
from scripts.store import check_id

PENDING_FILENAME = "pending.jsonl"


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text() == text:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _export(conn: sqlite3.Connection, state: Path) -> None:
    sprints, _ = sp.load_sprints(conn)
    for sprint in sprints:
        _write_if_changed(state / "sprints" / f"{check_id(sprint.id, 'sprint id')}.md", sprint.to_text())

    root = state / "knowledge"
    ensure_kb(root)
    facts, _ = kb.load_facts(conn)
    retired = kb.load_retired(conn)
    for fact in facts:
        _write_if_changed(root / "facts" / fact_filename(fact), fact.to_text())
    for fact in retired:
        _write_if_changed(root / "retired" / fact_filename(fact), fact.to_text())
        for stale in (root / "facts").glob(f"{fact.id}-*.md"):
            stale.unlink(missing_ok=True)  # the live copy of a now-retired fact
    today = datetime.now().strftime("%Y-%m-%d")
    _write_if_changed(root / "knowledge.md", generate_knowledge_index(facts, retired, today))

    # No `created` key: an older plugin builds PendingFact(**row) and would drop the line.
    pend = kb_pending_rows(conn)
    if pend or (root / PENDING_FILENAME).exists():
        _write_if_changed(root / PENDING_FILENAME, "".join(json.dumps(r) + "\n" for r in pend))


def kb_pending_rows(conn: sqlite3.Connection) -> list[dict]:
    from dataclasses import asdict

    from scripts.pending import load_pending

    return [asdict(p) for p in load_pending(conn)]


def export(conn: sqlite3.Connection, state: Path) -> bool:
    """Rewrite the views from the tables. Returns False (after a stderr
    warning) when the files could not be written."""
    from scripts import db

    try:
        # A legacy writer may have touched a file since this verb connected:
        # import it before the export would overwrite it.
        from scripts import migrate
        migrate.reimport_newer_files(conn, state, export=False)
        _export(conn, state)
        db.set_meta(conn, "views_exported_at", repr(time.time()))
        conn.commit()
        return True
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"warning: could not refresh the sprint/knowledge file views ({exc})",
              file=sys.stderr)
        return False
