"""Structural lint for reviewer/strategy markdown: verify required '##'
sections are present so a dropped-in lens/strategy is well-formed."""
from __future__ import annotations

import re
from pathlib import Path

_SECTIONS = {
    "strategy": ["Summary", "When to use", "Context handling", "Stages",
                 "Reconciliation", "Cost"],
    "reviewer": ["Concern", "When to seat", "Techniques", "What to look for",
                 "Severity", "Voice", "Allowed exceptions"],
}


def required_sections(kind: str) -> list[str]:
    return list(_SECTIONS[kind])


def lint_doc(path: Path, kind: str) -> list[str]:
    if not Path(path).exists():
        return [f"{path}: file missing"]
    text = Path(path).read_text()
    headings = set(re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    problems = []
    for want in required_sections(kind):
        if not any(h.startswith(want) for h in headings):
            problems.append(f"{path.name}: missing '## {want}' section")
    return problems
