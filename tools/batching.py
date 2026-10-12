"""Batch planner for rule-checking agents (WF-270; subagents.md 3.3, verdict change 5).

Stdlib only. A *unit* is one rulebook (a doctrine, an email doctrine, a django group, a clone persona) with an
ordered list of judgement rules. `plan_batches` returns *batches*; a batch is a set of id ranges, one per unit it
covers, and is what one `pip-agents:reviewer-rules` dispatch checks.

Rules, in order:
- a batch never holds more than BATCH_CAP rules;
- a unit over BATCH_CAP is split along its categories (consecutive rules with the same category stay together);
  a single category over BATCH_CAP is cut at BATCH_CAP;
- a unit of BATCH_FLOOR rules or more is never packed with another unit;
- when a split leaves a batch under BATCH_FLOOR (31 rules would be [30, 1]) it is merged with its neighbour and
  the pair rebalanced ([16, 15]); a unit under BATCH_FLOOR in total stays one batch;
- units under BATCH_FLOOR pack together only when their scope lists are identical AND declared (the same files
  are read for each); a unit with no scope is "unspecified", not "identical", and gets its own batch; at most
  BATCH_CAP rules per batch;
- the ranges of one unit tile its rules exactly, in order.
Consumers import the two constants for their own drift tests (for example `rules.BATCH_CAP == batching.BATCH_CAP`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

BATCH_CAP = 30
BATCH_FLOOR = 8


@dataclass(frozen=True)
class Unit:
    """One rulebook. `categories` is parallel to `rule_ids` (same length); `scope` is the files it reads."""

    name: str
    rule_ids: tuple[str, ...]
    categories: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.categories and len(self.categories) != len(self.rule_ids):
            raise ValueError(f"{self.name}: categories must be parallel to rule_ids")


@dataclass(frozen=True)
class Span:
    """Rules `start:end` (half-open, 0-based) of the unit called `unit`."""

    unit: str
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class Batch:
    spans: tuple[Span, ...] = field(default_factory=tuple)

    @property
    def size(self) -> int:
        return sum(s.size for s in self.spans)

    def ids(self, units: dict[str, Unit]) -> list[str]:
        return [rid for s in self.spans for rid in units[s.unit].rule_ids[s.start:s.end]]


def _category_runs(unit: Unit) -> list[tuple[int, int]]:
    """Half-open index runs of consecutive rules sharing a category (one run if the unit has no categories)."""
    n = len(unit.rule_ids)
    if not unit.categories:
        return [(0, n)]
    runs, start = [], 0
    for i in range(1, n + 1):
        if i == n or unit.categories[i] != unit.categories[start]:
            runs.append((start, i))
            start = i
    return runs


def _split(unit: Unit) -> list[Batch]:
    batches: list[Batch] = []
    cur_start = cur_end = 0
    for a, b in _category_runs(unit):
        while b - a > BATCH_CAP:  # one category alone is over the cap: flush, then cut it
            if cur_end > cur_start:
                batches.append(Batch((Span(unit.name, cur_start, cur_end),)))
            batches.append(Batch((Span(unit.name, a, a + BATCH_CAP),)))
            a += BATCH_CAP
            cur_start = cur_end = a
        if cur_end == cur_start:
            cur_start = a
        elif b - cur_start > BATCH_CAP:
            batches.append(Batch((Span(unit.name, cur_start, cur_end),)))
            cur_start = a
        cur_end = b
    if cur_end > cur_start:
        batches.append(Batch((Span(unit.name, cur_start, cur_end),)))
    return _rebalance(unit.name, batches)


def _rebalance(name: str, batches: list[Batch]) -> list[Batch]:
    """No batch of a split unit stays under BATCH_FLOOR: merge it into a neighbour, or cut the pair evenly."""
    if BATCH_CAP < 2 * BATCH_FLOOR:  # an even cut of an over-cap pair would leave both halves under the floor, forever
        raise ValueError(f"BATCH_CAP ({BATCH_CAP}) must be at least 2 * BATCH_FLOOR ({BATCH_FLOOR})")
    spans = [b.spans[0] for b in batches]
    i = 0
    while len(spans) > 1 and i < len(spans):
        if spans[i].size >= BATCH_FLOOR:
            i += 1
            continue
        j = i - 1 if i > 0 else i + 1
        lo, hi = min(i, j), max(i, j)
        start, end = spans[lo].start, spans[hi].end
        if end - start <= BATCH_CAP:
            spans[lo:hi + 1] = [Span(name, start, end)]
        else:
            mid = start + (end - start + 1) // 2
            spans[lo:hi + 1] = [Span(name, start, mid), Span(name, mid, end)]
        i = max(lo - 1, 0)
    return [Batch((s,)) for s in spans]


def plan_batches(units: list[Unit]) -> list[Batch]:
    names = [u.name for u in units]
    if len(set(names)) != len(names):
        raise ValueError("unit names must be unique")
    out: list[Batch] = []
    small: dict[tuple[str, ...], list[Unit]] = {}
    for u in units:
        n = len(u.rule_ids)
        if n == 0:
            continue
        if n >= BATCH_FLOOR:
            out += _split(u) if n > BATCH_CAP else [Batch((Span(u.name, 0, n),))]
        elif not u.scope:
            out.append(Batch((Span(u.name, 0, n),)))  # scope unspecified: never packed
        else:
            small.setdefault(u.scope, []).append(u)
    for group in small.values():
        cur: list[Span] = []
        size = 0
        for u in group:
            n = len(u.rule_ids)
            if size + n > BATCH_CAP:
                out.append(Batch(tuple(cur)))
                cur, size = [], 0
            cur.append(Span(u.name, 0, n))
            size += n
        if cur:
            out.append(Batch(tuple(cur)))
    return out
