"""Structural lint for reviewer/strategy markdown: verify required '##'
sections are present (exact heading match) so a dropped-in lens/strategy is
well-formed. A reviewer must also carry a parseable `allowed-exceptions`
block whose ids all exist in its "What to look for" table."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.contract import rule_id_of
from scripts.exceptions import ExceptionsError, parse_allowed_exceptions

_SECTIONS = {
    "strategy": ["Summary", "When to use", "Context handling", "Stages",
                 "Reconciliation", "Cost"],
    "reviewer": ["Concern", "When to seat", "Techniques", "What to look for",
                 "Severity", "Voice", "Allowed exceptions"],
}


def required_sections(kind: str) -> list[str]:
    return list(_SECTIONS[kind])


def _table_rule_ids(text: str) -> set[str]:
    """Rule ids in the first column of the '## What to look for' table."""
    ids: set[str] = set()
    in_section = False
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            in_section = m.group(1) == "What to look for"
            continue
        if in_section and line.lstrip().startswith("|"):
            first = line.strip().strip("|").split("|")[0].strip()
            rid = rule_id_of(first)
            if rid and rid == first:
                ids.add(rid)
    return ids


def lint_doc(path: Path | str, kind: str) -> list[str]:
    path = Path(path)
    if not path.exists():
        return [f"{path}: file missing"]
    text = path.read_text()
    headings = {h.strip() for h in re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)}
    problems = []
    for want in required_sections(kind):
        if want not in headings:
            problems.append(f"{path.name}: missing '## {want}' section")
    if kind == "reviewer":
        try:
            listed = parse_allowed_exceptions(text)
        except ExceptionsError as exc:
            problems.append(f"{path.name}: {exc}")
        else:
            known = _table_rule_ids(text)
            for rid in sorted(listed):
                if rid not in known:
                    problems.append(
                        f"{path.name}: allowed exception {rid} is not in 'What to look for'"
                    )
    return problems
