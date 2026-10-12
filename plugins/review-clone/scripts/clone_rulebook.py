"""A clone persona's rules as a rulebook for `pip-agents:reviewer-rules` (mirrors review-panel's `scripts/rulebook.py`;
tests/review-clone/test_gate.py pins the two together).

Each `### ` heading under `## Rules` is one rule, numbered `CLONE-<alias>-NNN` in file order. A batch is at most
BATCH_CAP rules (the vendored `tools/batching.py` planner, so the cap has one definition); its rulebook file lists the
rules with their ids, then the persona's "What they let go" as an Allowed exceptions span."""
from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "pip-agents"


def _load(stem: str):
    name = f"_review_clone_vendored_{stem}"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, VENDOR / "scripts" / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def validator():
    return _load("validate_result")


def batching():
    return _load("batching")


BATCH_CAP = batching().BATCH_CAP


@dataclass(frozen=True)
class Rule:
    id: str
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


def clone_rules(alias: str, body: str) -> list[Rule]:
    blocks: list[list[str]] = []
    for line in _section(body, "Rules"):
        if line.startswith("### "):
            blocks.append([line[4:].strip()])
        elif blocks:
            blocks[-1].append(line)
    out = []
    for n, block in enumerate(blocks, 1):
        rid = f"CLONE-{alias}-{n:03d}"
        out.append(Rule(rid, (f"### {rid} {block[0]}", *block[1:])))
    return out


def clone_exceptions(body: str) -> list[str]:
    lines = _section(body, "What they let go")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def render(name: str, rules: list[Rule], exceptions: list[str] | None = None) -> str:
    lines = [f"# {name} rules", ""]
    for r in rules:
        lines += list(r.lines)
        lines.append("")
    if exceptions:
        lines += ["## Allowed exceptions", *exceptions]
    return "\n".join(lines).rstrip() + "\n"


def plan(name: str, rules: list[Rule]) -> list[list[Rule]]:
    if not rules:
        return []
    b = batching()
    unit = b.Unit(name, tuple(r.id for r in rules))
    by_id = {r.id: r for r in rules}
    return [[by_id[i] for i in batch.ids({name: unit})] for batch in b.plan_batches([unit])]
