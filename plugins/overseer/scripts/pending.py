"""Pending Learned facts (WF-113 §5.5).

Agents report a ``learned`` array of ``{statement, tags}`` objects in their
``overseer-report`` JSON block (``scripts/schemas.py``); the report hook
queues each one here; the orchestrator adjudicates at a stage boundary —
accept (becomes a real KB fact) or reject (kept, with a reason, so the same
claim is recognisable if re-proposed). The queue is one JSONL file beside the
knowledge base: appends are the hot path (parallel hooks), status changes are
rare and rewrite the file atomically.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scripts.knowledge import knowledge_root

PENDING_FILENAME = "pending.jsonl"


@dataclass
class PendingFact:
    id: str
    card: str
    statement: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    status: str = "pending"
    reason: str = ""


def _path(repo_root: Path) -> Path:
    return knowledge_root(repo_root) / PENDING_FILENAME


def add_pending(
    repo_root: Path, card: str, statement: str, tags: list[str], source: str
) -> PendingFact:
    fact = PendingFact(
        id=f"P-{uuid.uuid4().hex[:6]}", card=card, statement=statement, tags=tags, source=source
    )
    path = _path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(asdict(fact)) + "\n")
    return fact


def load_pending(repo_root: Path) -> list[PendingFact]:
    path = _path(repo_root)
    if not path.exists():
        return []
    facts: list[PendingFact] = []
    for raw in path.read_text().splitlines():
        try:
            facts.append(PendingFact(**json.loads(raw)))
        except (ValueError, TypeError):
            continue
    return facts


def set_status(repo_root: Path, fact_id: str, status: str, reason: str = "") -> PendingFact:
    facts = load_pending(repo_root)
    match = next((f for f in facts if f.id == fact_id), None)
    if match is None:
        raise FileNotFoundError(f"no pending fact with id {fact_id}")
    if match.status != "pending":
        raise ValueError(f"{fact_id} is already {match.status}")
    match.status = status
    match.reason = reason
    path = _path(repo_root)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(asdict(f)) + "\n" for f in facts))
    os.replace(tmp, path)
    return match
