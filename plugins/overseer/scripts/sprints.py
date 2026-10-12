"""Sprints: the dataclass (with its legacy file form), board.db persistence and
card-table rollup. The ``sprints/<id>.md`` files are generated views."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

import yaml

from scripts.models import (
    Card,
    CardParseError,
    format_tokens,
    parse_tokens,
    split_frontmatter,
)
from scripts.db import commit_unless_txn
from scripts.store import check_id

SPRINT_STATUSES = {"planned", "active", "closed"}


@dataclass
class Sprint:
    id: str
    status: str = "planned"
    budget_estimate: int | None = None
    budget_actual: int = 0
    started: str = ""
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> "Sprint":
        meta, body = split_frontmatter(text)
        for key in ("id", "status"):
            if not meta.get(key):
                raise CardParseError(f"missing required field: {key}")
        status = str(meta["status"])
        if status not in SPRINT_STATUSES:
            raise CardParseError(f"unknown sprint status: {status!r}")
        budget = meta.get("budget") or {}
        return cls(
            id=str(meta["id"]),
            status=status,
            budget_estimate=parse_tokens(budget.get("estimate")),
            budget_actual=parse_tokens(budget.get("actual")) or 0,
            started=str(meta.get("started", "")),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "status": self.status,
            "budget": {
                "estimate": format_tokens(self.budget_estimate),
                "actual": format_tokens(self.budget_actual),
            },
            "started": self.started,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"


def replace_section(body: str, header: str, content: str) -> str:
    """Replace the content of the named `## ` section, creating it if absent."""
    lines = body.split("\n")
    if header not in lines:
        return f"{body.rstrip()}\n\n{header}\n{content}"
    start = lines.index(header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[: start + 1] + [content, ""] + lines[end:]).rstrip()


def rollup(sprint: Sprint, cards: list[Card]) -> Sprint:
    mine = sorted((c for c in cards if c.sprint == sprint.id), key=lambda c: c.id)
    rows = [
        "| Card | Complexity | Est | Actual | Status |",
        "|---|---|---|---|---|",
    ]
    for c in mine:
        est = format_tokens(c.budget_estimate) or "?"
        act = format_tokens(c.budget_actual) or "0"
        rows.append(f"| {c.id} | {c.complexity or '?'} | {est} | {act} | {c.status} |")
    estimates = [c.budget_estimate for c in mine if c.budget_estimate is not None]
    return dc_replace(
        sprint,
        body=replace_section(sprint.body, "## Cards", "\n".join(rows)),
        budget_actual=sum(c.budget_actual for c in mine),
        budget_estimate=sum(estimates) if estimates else None,
    )


def retro_rollup(sprint: Sprint, cards: list[Card]) -> Sprint:
    mine = sorted((c for c in cards if c.sprint == sprint.id), key=lambda c: c.id)
    rows = [
        "| Card | Est | Actual | Ratio | Status |",
        "|---|---|---|---|---|",
    ]
    for c in mine:
        est = format_tokens(c.budget_estimate) or "?"
        act = format_tokens(c.budget_actual) or "0"
        ratio = (f"{c.budget_actual / c.budget_estimate:.2f}×"
                 if c.budget_estimate else "—")
        rows.append(f"| {c.id} | {est} | {act} | {ratio} | {c.status} |")
    return dc_replace(
        sprint, body=replace_section(sprint.body, "## Retro", "\n".join(rows))
    )


def _row_to_sprint(row) -> Sprint:
    return Sprint(
        id=row["id"], status=row["status"], budget_estimate=row["budget_estimate"],
        budget_actual=row["budget_actual"] or 0, started=row["started"] or "",
        body=row["body"] or "",
    )


def sprint_exists(conn: sqlite3.Connection, sprint_id: str) -> bool:
    return conn.execute("SELECT 1 FROM sprints WHERE id = ?", (sprint_id,)).fetchone() is not None


def load_sprint(conn: sqlite3.Connection, sprint_id: str) -> Sprint:
    """One sprint; ``FileNotFoundError`` (the CLI's exit-1 'unknown id') if absent."""
    check_id(sprint_id, "sprint id")
    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    if row is None:
        raise FileNotFoundError(f"no sprint with id {sprint_id}")
    return _row_to_sprint(row)


def save_sprint(conn: sqlite3.Connection, sprint: Sprint, now: str = "") -> None:
    """Upsert one sprint. Call inside ``db.txn`` when it follows a load."""
    check_id(sprint.id, "sprint id")
    conn.execute(
        "INSERT INTO sprints(id, status, budget_estimate, budget_actual, started, body, updated) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
        "budget_estimate=excluded.budget_estimate, budget_actual=excluded.budget_actual, "
        "started=excluded.started, body=excluded.body, updated=excluded.updated",
        (sprint.id, sprint.status, sprint.budget_estimate, sprint.budget_actual,
         sprint.started, sprint.body, now),
    )
    commit_unless_txn(conn)


def load_sprints(conn: sqlite3.Connection) -> tuple[list[Sprint], list[Path]]:
    """All sprints, by id. Reads never mutate (OL-10): the second element is
    always empty now -- a typed row cannot be corrupt, and unparseable legacy
    files are reported by the importer and left in place."""
    rows = conn.execute("SELECT * FROM sprints ORDER BY id").fetchall()
    return [_row_to_sprint(r) for r in rows], []
