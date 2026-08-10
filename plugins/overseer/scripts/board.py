"""Complete board state export: all cards (live + archived) + sprints + computed relations."""
from __future__ import annotations

from pathlib import Path

from scripts import db
from scripts.relations import epic_rollup, is_epic, is_ready
from scripts.sprints import load_sprints
from scripts.store import state_root


def board_data(repo_root: Path) -> dict:
    """Export the complete board state as a single JSON-serializable dict.

    Returns:
        {
            "project": str,
            "cards": [
                {
                    "id": str,
                    "title": str,
                    "status": str,
                    "stage": str | None,
                    "complexity": str | None,
                    "priority": str | None,
                    "sprint": str | None,
                    "parent": str | None,
                    "depends_on": list[str],
                    "labels": list[str],
                    "links": list[dict],  # [{"label", "path"}, ...]
                    "order": int,
                    "budget": {"estimate": int | None, "actual": int},
                    "is_epic": bool,
                    "ready": bool,
                    "rollup": dict | None,  # Only when is_epic=True
                    "checklist": list[dict],  # [{"task", "subject", "status"}, ...]
                    "repo": str | None,  # top-level repo name the card originated from
                    "created": str,  # "%Y-%m-%d", set at new-card time
                    "updated": str,  # ISO minute ("%Y-%m-%dT%H:%M"), stamped by every mutator
                    "claimed_by": str | None,  # census session_id holding the claim
                    "claimed_at": str | None,  # ISO minute, like "updated"
                    "claim_acked": bool,  # meaningful only while claimed_by is set
                },
                ...
            ],
            "sprints": [
                {
                    "id": str,
                    "status": str,
                    "started": str,
                    "budget": {"estimate": int | None, "actual": int},
                },
                ...
            ],
            "quarantined": [str],  # Paths to quarantined cards and sprints
        }
    """
    conn = db.connect(repo_root)
    live_cards, card_quarantined = db.load_live_cards(conn)
    archived_cards = db.load_archived_cards(conn)
    sprints, sprint_quarantined = load_sprints(state_root(repo_root))

    # Pool = live + archived for ALL relation computes
    pool = live_cards + archived_cards

    # Export cards (sorted by id)
    cards_data = []
    for card in sorted(pool, key=lambda c: c.id):
        epic = is_epic(pool, card.id)
        rollup = epic_rollup(pool, card.id) if epic else None
        cards_data.append(
            {
                "id": card.id,
                "title": card.title,
                "body": card.body,
                "status": card.status,
                "stage": card.stage,
                "complexity": card.complexity,
                "priority": card.priority,
                "sprint": card.sprint,
                "parent": card.parent,
                "depends_on": card.depends_on,
                "labels": card.labels,
                "links": card.links,
                "order": card.order,
                "budget": {
                    "estimate": card.budget_estimate,
                    "actual": card.budget_actual,
                },
                "is_epic": epic,
                "ready": is_ready(card, pool),
                "rollup": rollup,
                "checklist": card.checklist,
                "repo": card.repo,
                "created": card.created,
                "updated": card.updated,
                "claimed_by": card.claimed_by,
                "claimed_at": card.claimed_at,
                "claim_acked": card.claim_acked,
            }
        )

    # Export sprints
    sprints_data = [
        {
            "id": s.id,
            "status": s.status,
            "started": s.started,
            "budget": {
                "estimate": s.budget_estimate,
                "actual": s.budget_actual,
            },
        }
        for s in sprints
    ]

    # Collect quarantined paths
    quarantined_paths = [str(p) for p in card_quarantined + sprint_quarantined]

    return {
        "project": repo_root.resolve().name,
        "cards": cards_data,
        "sprints": sprints_data,
        "quarantined": quarantined_paths,
    }
