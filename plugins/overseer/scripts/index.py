"""ledger.md generation. The index is a view; card files are the truth."""
from __future__ import annotations

from pathlib import Path

from scripts.models import Card, format_tokens
from scripts.relations import children, epic_rollup, is_epic, unmet_deps
from scripts.store import load_archived_cards, load_live_cards, state_root

RECENTLY_DONE_LIMIT = 5


def _budget_cell(card: Card) -> str:
    actual = format_tokens(card.budget_actual) or "0"
    estimate = format_tokens(card.budget_estimate) or "?"
    return f"{actual}/{estimate}"


def _readiness(card: Card, cards: list[Card]) -> str:
    if not card.depends_on:
        return ""
    unmet = unmet_deps(card, cards)
    return "ready" if not unmet else f"waiting on {', '.join(unmet)}"


def _epic_child_line(card: Card, cards: list[Card]) -> str:
    if card.status in ("done", "parked", "blocked"):
        state = card.status
    else:
        state = card.stage or "planned"
    parts = [state, _budget_cell(card)]
    ready = _readiness(card, cards)
    if ready:
        parts.append(ready)
    return f"    - {card.id}  {card.title}  " + " · ".join(parts)


def _in_flight_row(card: Card, cards: list[Card]) -> str:
    if card.status == "blocked":
        stage = "BLOCKED"
        note = card.blocked_on or "blocked"
    else:
        stage = card.stage or "—"
        if card.stage and card.stage.endswith("review"):
            rounds = card.review_rounds(card.stage)
            if rounds:
                stage = f"{stage} (r{rounds})"
        ready = _readiness(card, cards)
        note = ready if ready else ("2× BUDGET" if card.tripwire_breached else "—")
    return (
        f"| {card.id} | {card.title} | {stage} | {card.complexity or '?'} "
        f"| {_budget_cell(card)} | {note} |"
    )


def generate_index(
    project: str,
    cards: list[Card],
    recently_done: list[Card],
    now: str,
    pool: list[Card] | None = None,
) -> str:
    pool = cards if pool is None else pool
    epics = sorted((c for c in cards if is_epic(pool, c.id)), key=lambda c: c.id)
    standalone = [c for c in cards if c.parent is None and not is_epic(pool, c.id)]
    in_flight = [c for c in standalone if c.status in ("in-flight", "blocked")]
    planned = [c for c in standalone if c.status == "planned"]
    parked = [c for c in standalone if c.status == "parked"]

    lines = [f"# Ledger — {project}", f"Updated: {now}", ""]

    if epics:
        lines.append("## Epics")
        for e in epics:
            r = epic_rollup(pool, e.id)
            est = format_tokens(r["estimate"]) or "0"
            act = format_tokens(r["actual"]) or "0"
            lines.append(
                f"- {e.id} — {e.title}  ({r['done']}/{r['total']} done · {act}/{est})"
            )
            for kid in sorted(children(pool, e.id), key=lambda c: c.id):
                lines.append(_epic_child_line(kid, pool))
        lines.append("")

    lines.append("## In flight")
    if in_flight:
        lines += [
            "| Card | Title | Stage | Complexity | Budget (act/est) | Note |",
            "|---|---|---|---|---|---|",
        ]
        lines += [_in_flight_row(c, pool) for c in in_flight]
    else:
        lines.append("_Nothing in flight._")

    lines += ["", "## Planned"]
    if planned:
        for c in planned:
            estimate = format_tokens(c.budget_estimate) or "?"
            sprint = f", sprint {c.sprint}" if c.sprint else ""
            ready = _readiness(c, pool)
            suffix = f" · {ready}" if ready else ""
            lines.append(
                f"- {c.id} — {c.title} ({c.complexity or '?'}, ~{estimate}{sprint}){suffix}"
            )
    else:
        lines.append("_Backlog empty._")

    if parked:
        lines += ["", "## Parked"]
        for c in parked:
            day = c.updated[:10] if c.updated else "?"
            lines.append(f"- {c.id} — {c.title} (shelved {day})")

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
    archived = load_archived_cards(root)
    recently_done = archived[:RECENTLY_DONE_LIMIT]
    (root / "ledger.md").write_text(
        generate_index(project, cards, recently_done, now, pool=cards + archived)
    )
    return quarantined
