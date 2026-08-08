"""Derived card relationships: epics (parent), dependencies, readiness, cycles.

Pure functions over a card list — no I/O, no mutation. Unknown/missing referenced
ids are surfaced (treated as unmet/absent), never raised.
"""
from __future__ import annotations

from scripts.models import Card


def _by_id(cards: list[Card]) -> dict[str, Card]:
    return {c.id: c for c in cards}


def children(cards: list[Card], parent_id: str) -> list[Card]:
    return [c for c in cards if c.parent == parent_id]


def is_epic(cards: list[Card], card_id: str) -> bool:
    return any(c.parent == card_id for c in cards)


def epic_rollup(cards: list[Card], card_id: str) -> dict:
    kids = children(cards, card_id)
    return {
        "done": sum(1 for c in kids if c.status == "done"),
        "total": len(kids),
        "estimate": sum(c.budget_estimate or 0 for c in kids),
        "actual": sum(c.budget_actual for c in kids),
    }


def unmet_deps(card: Card, cards: list[Card]) -> list[str]:
    index = _by_id(cards)
    unmet: list[str] = []
    for dep in card.depends_on:
        target = index.get(dep)
        if target is None or target.status != "done":
            unmet.append(dep)
    return unmet


def is_ready(card: Card, cards: list[Card]) -> bool:
    return not unmet_deps(card, cards)


def would_cycle_parent(cards: list[Card], card_id: str, new_parent: str) -> bool:
    """True if setting card_id.parent = new_parent would create a cycle."""
    if new_parent == card_id:
        return True
    index = _by_id(cards)
    cur = index.get(new_parent)
    seen: set[str] = set()
    while cur is not None and cur.id not in seen:
        if cur.id == card_id:
            return True
        seen.add(cur.id)
        cur = index.get(cur.parent) if cur.parent else None
    return False


def would_cycle_depends(cards: list[Card], card_id: str, new_dep: str) -> bool:
    """True if adding card_id -> depends_on new_dep would create a cycle."""
    if new_dep == card_id:
        return True
    index = _by_id(cards)
    stack = [new_dep]
    seen: set[str] = set()
    while stack:
        cur_id = stack.pop()
        if cur_id == card_id:
            return True
        if cur_id in seen:
            continue
        seen.add(cur_id)
        cur = index.get(cur_id)
        if cur is not None:
            stack.extend(cur.depends_on)
    return False
