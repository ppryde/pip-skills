"""Budgeted text output. Whole rows only; counts say whether they are exact or lower bounds;
seeds (verdicts) are never cut; every section is named and gets a first row before any section
gets a second; whatever does not fit is named, never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 3
TAIL_RESERVE = 24  # room for "  +NNNN more (exact)\n", reserved with each non-seed header


def est_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


@dataclass
class Section:
    title: str
    rows: list[str]
    total: int | None = None
    exact: bool = True
    seed: bool = False

    @property
    def count(self) -> int:
        return self.total if self.total is not None else len(self.rows)

    @property
    def head(self) -> str:
        return f"## {self.title} ({self.count}{'' if self.exact else '+'})"


def render(header: list[str], sections: list[Section], footer: list[str],
           budget_tokens: int, stats: dict[str, object] | None = None) -> str:
    budget = budget_tokens * CHARS_PER_TOKEN
    used = sum(len(line) + 1 for line in [*header, *footer])
    live = [s for s in sections if s.count > 0]
    ordered = [s for s in live if s.seed] + [s for s in live if not s.seed]
    shown: dict[int, int] = {}
    omitted: list[str] = []
    for i, sec in enumerate(ordered):  # pass 1: seeds whole, then every header
        if sec.seed:
            shown[i] = len(sec.rows)
            used += sum(len(line) + 1 for line in [sec.head, *sec.rows])
        elif used + len(sec.head) + 1 + TAIL_RESERVE <= budget:
            shown[i] = 0
            used += len(sec.head) + 1 + TAIL_RESERVE
        else:
            omitted.append(f"{sec.title} ({sec.count})")
    for limit in (1, None):  # pass 2: a first row each; pass 3: the rest, in priority order
        for i, sec in enumerate(ordered):
            if i not in shown or sec.seed:
                continue
            while shown[i] < len(sec.rows) and (limit is None or shown[i] < limit):
                cost = len(sec.rows[shown[i]]) + 1
                if used + cost > budget:
                    break
                used += cost
                shown[i] += 1
    out = list(header)
    cut: dict[str, int] = {}
    for i, sec in enumerate(ordered):
        if i not in shown:
            continue
        out.append(sec.head)
        out.extend(sec.rows[:shown[i]])
        hidden = sec.count - shown[i]
        if hidden > 0:
            out.append(f"  +{hidden} more ({'exact' if sec.exact else '≥'})")
            cut[sec.title] = hidden
    if omitted:
        out.append("omitted for budget: " + ", ".join(omitted)
                   + " (rerun with a larger --budget or the section's own command)")
    out.extend(footer)
    if stats is not None:
        stats.update(budget=budget_tokens, cut=cut, omitted=[o.rsplit(" (", 1)[0] for o in omitted])
    return "\n".join(out)
