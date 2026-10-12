"""Knowledge base: Fact parse/serialise, staleness, store ops, index."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from scripts.models import CardParseError, split_frontmatter
from scripts.db import commit_unless_txn
from scripts.store import check_id, slugify, state_root

FACT_STATUSES = {"active", "stale", "retired"}
STALE_DAYS = 90
_MINTED_FACT_RE = re.compile(r"\AKB-(\d+)-")


class FactParseError(ValueError):
    """A fact file that cannot be parsed or fails validation."""


def is_stale(verified: str, today: str, max_age_days: int = STALE_DAYS) -> bool:
    if not verified:
        return False
    try:
        v = datetime.strptime(verified[:10], "%Y-%m-%d")
        t = datetime.strptime(today[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return (t - v).days > max_age_days


@dataclass
class Fact:
    """One falsifiable statement with provenance and a verification date."""

    id: str
    statement: str
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    created: str = ""
    verified: str = ""
    status: str = "active"
    superseded_by: str | None = None
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> Fact:
        try:
            meta, body = split_frontmatter(text)
        except CardParseError as exc:
            raise FactParseError(str(exc)) from exc
        for key in ("id", "statement"):
            if not meta.get(key):
                raise FactParseError(f"missing required field: {key}")
        status = str(meta.get("status", "active"))
        if status not in FACT_STATUSES:
            raise FactParseError(f"unknown status: {status!r}")
        tags_raw = meta.get("tags")
        if isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        elif tags_raw:
            tags = [str(tags_raw)]
        else:
            tags = []
        return cls(
            id=str(meta["id"]),
            statement=str(meta["statement"]),
            tags=tags,
            source=meta.get("source"),
            created=str(meta.get("created", "")),
            verified=str(meta.get("verified", "")),
            status=status,
            superseded_by=meta.get("superseded_by"),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "statement": self.statement,
            "tags": self.tags or None,
            "source": self.source,
            "created": self.created,
            "verified": self.verified,
            "status": self.status,
            "superseded_by": self.superseded_by,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"

    def effective_status(self, today: str) -> str:
        if self.status == "active" and is_stale(self.verified, today):
            return "stale"
        return self.status


def knowledge_root(repo_root: Path) -> Path:
    """Where the generated ``knowledge/`` view tree lives (not the source of truth)."""
    return state_root(repo_root) / "knowledge"


def ensure_kb(kb: Path) -> None:
    for sub in ("facts", "retired", "corrupt"):
        (kb / sub).mkdir(parents=True, exist_ok=True)


def fact_filename(fact: Fact) -> str:
    return f"{fact.id}-{slugify(fact.statement)}.md"


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        id=row["id"], statement=row["statement"], tags=json.loads(row["tags"] or "[]"),
        source=row["source"], created=row["created"] or "", verified=row["verified"] or "",
        status=row["status"], superseded_by=row["superseded_by"], body=row["body"] or "",
    )


def mint_fact_id(conn: sqlite3.Connection) -> str:
    """Next ``KB-nnn``. Call inside the ``db.txn`` that inserts the fact so two
    concurrent adds cannot mint the same id."""
    highest = 0
    for (fid,) in conn.execute("SELECT id FROM facts"):
        match = _MINTED_FACT_RE.match(f"{fid}-")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"KB-{highest + 1:03d}"


def save_fact(conn: sqlite3.Connection, fact: Fact) -> None:
    """Upsert one fact (``retired`` follows ``status``)."""
    check_id(fact.id, "fact id")
    conn.execute(
        "INSERT INTO facts(id, statement, tags, source, status, verified, created, body, "
        "retired, superseded_by) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "statement=excluded.statement, tags=excluded.tags, source=excluded.source, "
        "status=excluded.status, verified=excluded.verified, created=excluded.created, "
        "body=excluded.body, retired=excluded.retired, superseded_by=excluded.superseded_by",
        (fact.id, fact.statement, json.dumps(fact.tags), fact.source, fact.status,
         fact.verified, fact.created, fact.body, int(fact.status == "retired"),
         fact.superseded_by),
    )
    commit_unless_txn(conn)


def load_fact(conn: sqlite3.Connection, fact_id: str) -> Fact:
    """One LIVE fact; ``FileNotFoundError`` if absent or retired."""
    check_id(fact_id, "fact id")
    row = conn.execute("SELECT * FROM facts WHERE id = ? AND retired = 0", (fact_id,)).fetchone()
    if row is None:
        raise FileNotFoundError(f"no live fact with id {fact_id}")
    return _row_to_fact(row)


def load_facts(conn: sqlite3.Connection) -> tuple[list[Fact], list[Path]]:
    """Live facts by id. Reads never mutate (OL-10); the second element is
    always empty (kept for the callers' tuple shape)."""
    rows = conn.execute("SELECT * FROM facts WHERE retired = 0 ORDER BY id").fetchall()
    return [_row_to_fact(r) for r in rows], []


def load_retired(conn: sqlite3.Connection) -> list[Fact]:
    rows = conn.execute("SELECT * FROM facts WHERE retired = 1 ORDER BY id").fetchall()
    return [_row_to_fact(r) for r in rows]


def retire_fact(conn: sqlite3.Connection, fact: Fact) -> None:
    fact.status = "retired"
    save_fact(conn, fact)


def generate_knowledge_index(
    facts: list[Fact], retired: list[Fact], now: str
) -> str:
    active = [f for f in facts if f.status == "active"]
    stale = [f for f in facts if f.status == "stale"]

    lines = [f"# Knowledge — {len(active)} active", f"Updated: {now}", ""]
    lines.append("## Active")
    if active:
        lines += ["| Fact | Statement | Tags | Verified |", "|---|---|---|---|"]
        for f in active:
            tags = ", ".join(f.tags) or "—"
            lines.append(f"| {f.id} | {f.statement} | {tags} | {f.verified or '?'} |")
    else:
        lines.append("_No active facts._")

    lines += ["", "## Stale — verify before trusting"]
    if stale:
        for f in stale:
            tags = ", ".join(f.tags) or "—"
            lines.append(f"- {f.id} — {f.statement} ({tags}, last verified {f.verified or '?'})")
    else:
        lines.append("_None._")

    lines += ["", f"## Retired: {len(retired)}",
              "See `retired/` for superseded and refuted facts."]
    return "\n".join(lines) + "\n"


def refresh_stale(conn: sqlite3.Connection, today: str) -> int:
    """Persist the active -> stale flip for facts past ``STALE_DAYS``. Returns
    how many changed. Call inside the writer's ``db.txn``."""
    changed = 0
    facts, _ = load_facts(conn)
    for fact in facts:
        effective = fact.effective_status(today)
        if effective != fact.status:
            fact.status = effective
            save_fact(conn, fact)
            changed += 1
    return changed
