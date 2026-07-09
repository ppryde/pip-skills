"""Pure file-overlap detection across cards. No writes."""
from __future__ import annotations

from scripts.models import Card

_ACTIVE = ("planned", "in-flight")


def _norm(p: str) -> str:
    return p.strip().rstrip("/")


def paths_overlap(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _pair_overlap(a: Card, b: Card) -> list[str]:
    hits: set[str] = set()
    for pa in a.touches:
        for pb in b.touches:
            if paths_overlap(pa, pb):
                na, nb = _norm(pa), _norm(pb)
                hits.add(na if na == nb else f"{na} ~ {nb}")
    return sorted(hits)


def find_conflicts(cards: list[Card]) -> list[tuple[str, str, list[str]]]:
    live = [c for c in cards if c.status in _ACTIVE]
    out: list[tuple[str, str, list[str]]] = []
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            overlap = _pair_overlap(live[i], live[j])
            if overlap:
                out.append((live[i].id, live[j].id, overlap))
    return out
