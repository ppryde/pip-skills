"""ledger.md generation. The index is a view; card files are the truth."""
from __future__ import annotations

from pathlib import Path

from scripts.models import Card, format_tokens
from scripts.store import load_archived_cards, load_live_cards, state_root

RECENTLY_DONE_LIMIT = 5


def _budget_cell(card: Card) -> str:
    actual = format_tokens(card.budget_actual) or "0"
    estimate = format_tokens(card.budget_estimate) or "?"
    return f"{actual}/{estimate}"


def _in_flight_row(card: Card) -> str:
    if card.status == "blocked":
        stage = "BLOCKED"
        note = card.blocked_on or "blocked"
    else:
        stage = card.stage or "—"
        if card.stage and card.stage.endswith("review"):
            rounds = card.review_rounds(card.stage)
            if rounds:
                stage = f"{stage} (r{rounds})"
        note = "2× BUDGET" if card.tripwire_breached else "—"
    return (
        f"| {card.id} | {card.title} | {stage} | {card.complexity or '?'} "
        f"| {_budget_cell(card)} | {note} |"
    )


def generate_index(
    project: str, cards: list[Card], recently_done: list[Card], now: str
) -> str:
    in_flight = [c for c in cards if c.status in ("in-flight", "blocked")]
    planned = [c for c in cards if c.status == "planned"]

    lines = [f"# Ledger — {project}", f"Updated: {now}", "", "## In flight"]
    if in_flight:
        lines += [
            "| Card | Title | Stage | Complexity | Budget (act/est) | Note |",
            "|---|---|---|---|---|---|",
        ]
        lines += [_in_flight_row(c) for c in in_flight]
    else:
        lines.append("_Nothing in flight._")

    lines += ["", "## Planned"]
    if planned:
        for c in planned:
            estimate = format_tokens(c.budget_estimate) or "?"
            sprint = f", sprint {c.sprint}" if c.sprint else ""
            lines.append(f"- {c.id} — {c.title} ({c.complexity or '?'}, ~{estimate}{sprint})")
    else:
        lines.append("_Backlog empty._")

    lines += ["", "## Recently done"]
    if recently_done:
        for c in recently_done:
            day = c.updated[:10] if c.updated else "?"
            lines.append(f"- {c.id} — {c.status} {day}, {_budget_cell(c)}")
    else:
        lines.append("_Nothing yet._")

    return "\n".join(lines) + "\n"


def rebuild_index(repo_root: Path, project: str, now: str) -> list[Path]:
    root = state_root(repo_root)
    cards, quarantined = load_live_cards(root)
    recently_done = load_archived_cards(root)[:RECENTLY_DONE_LIMIT]
    (root / "ledger.md").write_text(generate_index(project, cards, recently_done, now))
    return quarantined
