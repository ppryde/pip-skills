"""Session-start resume detection: what was in flight, and at what stage."""
from __future__ import annotations

from pathlib import Path

from scripts.models import Card, format_tokens
from scripts.store import load_live_cards, workflow_root


def _entry(repo_root: Path, card: Card) -> dict:
    worktree_exists = card.worktree is not None and (repo_root / card.worktree).is_dir()
    round_no = (
        card.review_rounds(card.stage)
        if card.stage and card.stage.endswith("review")
        else 0
    )
    actual = format_tokens(card.budget_actual) or "0"
    estimate = format_tokens(card.budget_estimate) or "?"
    return {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "stage": card.stage,
        "round": round_no,
        "branch": card.branch,
        "pr": card.pr,
        "worktree": card.worktree,
        "worktree_exists": worktree_exists,
        "blocked_on": card.blocked_on,
        "budget": f"{actual}/{estimate}",
    }


def resume_entries(repo_root: Path) -> list[dict]:
    cards, _ = load_live_cards(workflow_root(repo_root))
    return [
        _entry(repo_root, c) for c in cards if c.status in ("in-flight", "blocked")
    ]


def format_report(entries: list[dict]) -> str:
    if not entries:
        return "Nothing in flight — clean slate."
    lines = []
    for e in entries:
        stage = f"BLOCKED ({e['blocked_on']})" if e["status"] == "blocked" else e["stage"]
        if e["round"]:
            stage = f"{stage}, round {e['round']}"
        worktree = e["worktree"] or "no worktree"
        if e["worktree"] and not e["worktree_exists"]:
            worktree += " (MISSING)"
        line = f"- {e['id']} — {e['title']}: {stage} | {worktree} | {e['budget']}"
        if e["pr"]:
            line += f" | PR: {e['pr']}"
        lines.append(line)
    return "\n".join(lines)
