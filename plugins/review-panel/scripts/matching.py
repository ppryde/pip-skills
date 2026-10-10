"""Pair the findings of two independent passes (dual-tiebreaker) in code, so
only genuine disagreements reach the arbiter."""
from __future__ import annotations

from dataclasses import dataclass, replace

from scripts.contract import VALID_SEVERITY, Finding, norm as _norm


@dataclass
class MatchResult:
    agreed: list[Finding]   # A's finding, higher severity kept, verdict confirmed
    only_a: list[Finding]
    only_b: list[Finding]


def _same_kind(a: Finding, b: Finding) -> bool:
    if a.rule_id and b.rule_id:
        # Two distinct rules never auto-confirm each other, even in one category.
        return a.rule_id == b.rule_id
    return _norm(a.category) == _norm(b.category)


def _pairs(a: Finding, b: Finding, window: int) -> bool:
    if a.reviewer != b.reviewer or a.file != b.file:
        return False
    if a.line is None and b.line is None:
        # No line to compare: agree only on the same rule.
        same_rule = (a.rule_id and a.rule_id == b.rule_id) or _norm(a.rule) == _norm(b.rule)
        return bool(same_rule)
    if a.line is None or b.line is None:
        return False
    return abs(a.line - b.line) <= window and _same_kind(a, b)


def _distance(a: Finding, b: Finding) -> tuple[int, int]:
    dist = 0 if a.line is None or b.line is None else abs(a.line - b.line)
    return (dist, 0 if a.rule_id and a.rule_id == b.rule_id else 1)


def _higher(a: str, b: str) -> str:
    return a if VALID_SEVERITY.index(a) <= VALID_SEVERITY.index(b) else b


def match(a: list[Finding], b: list[Finding], window: int = 3) -> MatchResult:
    """One-to-one pairing: each B finding is used at most once, so a duplicate
    inside one pass stays unmatched rather than agreeing twice."""
    taken: set[int] = set()
    agreed: list[Finding] = []
    only_a: list[Finding] = []
    for fa in a:
        best: int | None = None
        for j, fb in enumerate(b):
            if j in taken or not _pairs(fa, fb, window):
                continue
            if best is None or _distance(fa, fb) < _distance(fa, b[best]):
                best = j
        if best is None:
            only_a.append(fa)
            continue
        taken.add(best)
        agreed.append(replace(
            fa,
            severity=_higher(fa.severity, b[best].severity),
            verdict="confirmed",
            reason="both passes",
        ))
    only_b = [fb for j, fb in enumerate(b) if j not in taken]
    return MatchResult(agreed, only_a, only_b)
