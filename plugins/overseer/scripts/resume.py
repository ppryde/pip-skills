"""Session-start resume detection: what was in flight, and at what stage."""
from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.models import Card, format_tokens
from scripts.store import load_live_cards, state_root


def _branch_exists(repo_root: Path, branch: str | None) -> bool:
    if not branch:
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo_root,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _entry(repo_root: Path, card: Card) -> dict:
    worktree_exists = card.worktree is not None and (repo_root / card.worktree).is_dir()
    branch_exists = _branch_exists(repo_root, card.branch)
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
        "branch_exists": branch_exists,
        "pr": card.pr,
        "worktree": card.worktree,
        "worktree_exists": worktree_exists,
        "blocked_on": card.blocked_on,
        "budget": f"{actual}/{estimate}",
    }


def resume_entries(repo_root: Path) -> list[dict]:
    cards, _ = load_live_cards(state_root(repo_root))
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
        if e["branch"] and not e["branch_exists"]:
            line += " (branch MISSING)"
        if e["pr"]:
            line += f" | PR: {e['pr']}"
        lines.append(line)
    return "\n".join(lines)


def handoff_data(repo_root: Path) -> dict:
    """Everything a fresh session needs, derived in one scan."""
    root = state_root(repo_root)
    cards, quarantined = load_live_cards(root)
    entries = [_entry(repo_root, c) for c in cards
               if c.status in ("in-flight", "blocked")]
    live_branches: dict[str, list[str]] = {}
    for c in cards:
        if c.status in ("in-flight", "blocked") and c.branch:
            live_branches.setdefault(c.branch, []).append(c.id)
    return {
        "project": repo_root.resolve().name,
        "in_flight": [e for e in entries if e["status"] == "in-flight"],
        "blocked": [e for e in entries if e["status"] == "blocked"],
        "planned": [{"id": c.id, "title": c.title, "complexity": c.complexity}
                    for c in cards if c.status == "planned"],
        "stacks": {b: ids for b, ids in live_branches.items() if len(ids) > 1},
        "quarantined": [str(p) for p in quarantined],
    }


def handoff_report(repo_root: Path, data: dict | None = None) -> str:
    data = data or handoff_data(repo_root)
    lines = [f"# Handoff briefing — {data['project']}", ""]
    lines.append("## In flight")
    lines.append(format_report(data["in_flight"]) if data["in_flight"]
                 else "Nothing in flight — clean slate.")
    lines += ["", "## Blocked"]
    lines.append(format_report(data["blocked"]) if data["blocked"] else "_None._")
    lines += ["", "## Planned"]
    if data["planned"]:
        lines += [f"- {p['id']} — {p['title']} ({p['complexity'] or '?'})"
                  for p in data["planned"]]
    else:
        lines.append("_Backlog empty._")
    if data["stacks"]:
        lines += ["", "## Stacks"]
        lines += [f"- {branch}: {', '.join(ids)}"
                  for branch, ids in sorted(data["stacks"].items())]
    if data["quarantined"]:
        lines += ["", "## Quarantined during this scan"]
        lines += [f"- {p}" for p in data["quarantined"]]
    lines += ["", "## Resume",
              "In a fresh session, invoke the overseer ledger skill and run:",
              f"    python plugins/overseer/scripts/cli.py --root {repo_root} resume"]
    return "\n".join(lines) + "\n"
