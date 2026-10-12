"""Turn a reviewer's rules into the files a `reviewer-rules` seat reads.

A rules-lens seat is handed a *rulebook file* (`rules: <path> L1-<n> (<ids>)`): the rules to judge, each with its id,
at most BATCH_CAP per batch. A builtin reviewer's rules are the rows of its "What to look for" table; a clone
persona's are its `### ` headings under `## Rules`, numbered `CLONE-<alias>-NNN` in file order. Splitting is the
shared planner (`tools/batching.py`, vendored), so the cap has one definition."""
from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.contract import rule_id_of
from scripts.pip_agents import batching

BATCH_CAP = batching().BATCH_CAP


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    lines: tuple[str, ...]


def _section(text: str, name: str) -> list[str]:
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            inside = m.group(1) == name
            continue
        if inside:
            out.append(line)
    return out


def table_rules(text: str) -> tuple[tuple[str, ...], list[Rule]]:
    """(header rows, rules) of the "What to look for" table; a row whose first cell is not a rule id is skipped."""
    header: list[str] = []
    rules: list[Rule] = []
    for line in _section(text, "What to look for"):
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rid = rule_id_of(cells[0])
        if rid and rid == cells[0]:
            rules.append(Rule(rid, cells[1] if len(cells) > 1 else "", (line,)))
        elif not rules:
            header.append(line)
    return tuple(header), rules


def clone_rules(alias: str, body: str) -> list[Rule]:
    """The clone persona's rules, one per `### ` heading under `## Rules`, in file order."""
    blocks: list[list[str]] = []
    for line in _section(body, "Rules"):
        if line.startswith("### "):
            blocks.append([line[4:].strip()])
        elif blocks:
            blocks[-1].append(line)
    out = []
    for n, block in enumerate(blocks, 1):
        rid = f"CLONE-{alias}-{n:03d}"
        out.append(Rule(rid, "", (f"### {rid} {block[0]}", *block[1:])))
    return out


def clone_exceptions(body: str) -> list[str]:
    """The persona's "What they let go" lines (blank edges trimmed): what the rules lens must not report."""
    lines = _section(body, "What they let go")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def render(name: str, rules: list[Rule], header: tuple[str, ...] = (), exceptions: list[str] | None = None) -> str:
    """The rulebook file text for one batch. `exceptions` become an "Allowed exceptions" span after the rules."""
    lines = [f"# {name} rules", ""]
    lines += list(header)
    for r in rules:
        lines += list(r.lines)
        if r.lines and r.lines[0].startswith("###"):
            lines.append("")
    if exceptions:
        lines += ["## Allowed exceptions", *exceptions]
    return "\n".join(lines).rstrip() + "\n"


def plan(name: str, rules: list[Rule]) -> list[list[Rule]]:
    """The rules cut into batches of at most BATCH_CAP, in order, none a runt."""
    if not rules:
        return []
    b = batching()
    unit = b.Unit(name, tuple(r.id for r in rules), tuple(r.category for r in rules))
    by_id = {r.id: r for r in rules}
    units = {name: unit}
    return [[by_id[i] for i in batch.ids(units)] for batch in b.plan_batches([unit])]
