"""Sprint files: parse/serialise and card-table rollup."""
from __future__ import annotations

from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

import yaml

from scripts.models import (
    Card,
    CardParseError,
    format_tokens,
    parse_tokens,
    split_frontmatter,
)

SPRINT_STATUSES = {"planned", "active", "closed"}


@dataclass
class Sprint:
    id: str
    status: str = "planned"
    budget_estimate: int | None = None
    budget_actual: int = 0
    started: str = ""
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> "Sprint":
        meta, body = split_frontmatter(text)
        for key in ("id", "status"):
            if not meta.get(key):
                raise CardParseError(f"missing required field: {key}")
        status = str(meta["status"])
        if status not in SPRINT_STATUSES:
            raise CardParseError(f"unknown sprint status: {status!r}")
        budget = meta.get("budget") or {}
        return cls(
            id=str(meta["id"]),
            status=status,
            budget_estimate=parse_tokens(budget.get("estimate")),
            budget_actual=parse_tokens(budget.get("actual")) or 0,
            started=str(meta.get("started", "")),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "status": self.status,
            "budget": {
                "estimate": format_tokens(self.budget_estimate),
                "actual": format_tokens(self.budget_actual),
            },
            "started": self.started,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"


def replace_section(body: str, header: str, content: str) -> str:
    """Replace the content of the named `## ` section, creating it if absent."""
    lines = body.split("\n")
    if header not in lines:
        return f"{body.rstrip()}\n\n{header}\n{content}"
    start = lines.index(header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[: start + 1] + [content, ""] + lines[end:]).rstrip()


def rollup(sprint: Sprint, cards: list[Card]) -> Sprint:
    mine = sorted((c for c in cards if c.sprint == sprint.id), key=lambda c: c.id)
    rows = [
        "| Card | Complexity | Est | Actual | Status |",
        "|---|---|---|---|---|",
    ]
    for c in mine:
        est = format_tokens(c.budget_estimate) or "?"
        act = format_tokens(c.budget_actual) or "0"
        rows.append(f"| {c.id} | {c.complexity or '?'} | {est} | {act} | {c.status} |")
    estimates = [c.budget_estimate for c in mine if c.budget_estimate is not None]
    return dc_replace(
        sprint,
        body=replace_section(sprint.body, "## Cards", "\n".join(rows)),
        budget_actual=sum(c.budget_actual for c in mine),
        budget_estimate=sum(estimates) if estimates else None,
    )


def retro_rollup(sprint: Sprint, cards: list[Card]) -> Sprint:
    mine = sorted((c for c in cards if c.sprint == sprint.id), key=lambda c: c.id)
    rows = [
        "| Card | Est | Actual | Ratio | Status |",
        "|---|---|---|---|---|",
    ]
    for c in mine:
        est = format_tokens(c.budget_estimate) or "?"
        act = format_tokens(c.budget_actual) or "0"
        ratio = (f"{c.budget_actual / c.budget_estimate:.2f}×"
                 if c.budget_estimate else "—")
        rows.append(f"| {c.id} | {est} | {act} | {ratio} | {c.status} |")
    return dc_replace(
        sprint, body=replace_section(sprint.body, "## Retro", "\n".join(rows))
    )


def sprint_path(root: Path, sprint_id: str) -> Path:
    return root / "sprints" / f"{sprint_id}.md"


def load_sprint(path: Path) -> Sprint:
    return Sprint.from_text(path.read_text())


def save_sprint(root: Path, sprint: Sprint) -> Path:
    path = sprint_path(root, sprint.id)
    path.write_text(sprint.to_text())
    return path
