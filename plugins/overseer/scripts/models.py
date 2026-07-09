"""Card data model: frontmatter parse/serialise, token arithmetic, mutations."""
from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

STATUSES = {"planned", "in-flight", "blocked", "done", "abandoned"}
STAGES = [
    "bootstrap",
    "planning",
    "plan-review",
    "implementation",
    "impl-review",
    "verification",
    "awaiting-merge",
]

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_TOKENS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kM])?")


class CardParseError(ValueError):
    """A card file that cannot be parsed or fails validation."""


def parse_tokens(value: str | int | float | None) -> int | None:
    """'400k' -> 400_000, '2.1M' -> 2_100_000, 999 -> 999. None passes through."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = _TOKENS_RE.fullmatch(str(value).strip())
    if match is None:
        raise CardParseError(f"unparseable token count: {value!r}")
    multiplier = {"k": 1_000, "M": 1_000_000}.get(match.group(2) or "", 1)
    return int(float(match.group(1)) * multiplier)


def format_tokens(n: int | None) -> str | None:
    """400_000 -> '400k', 2_100_000 -> '2.1M', 999 -> '999'. None passes through."""
    if n is None:
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1_000:
        return f"{n / 1_000:g}k"
    return str(n)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown document into (frontmatter mapping, body)."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise CardParseError("no frontmatter block found")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise CardParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise CardParseError("frontmatter is not a mapping")
    return meta, match.group(2)


def append_to_section(body: str, header: str, content: str) -> str:
    """Insert content at the end of the named `## ` section, creating it if absent."""
    lines = body.split("\n")
    if header not in lines:
        return f"{body.rstrip()}\n\n{header}\n{content}"
    start = lines.index(header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    while end - 1 > start and lines[end - 1].strip() == "":
        end -= 1
    lines.insert(end, content)
    return "\n".join(lines)


@dataclass
class Card:
    """One unit of work. The card file is the source of truth; the index is a view."""

    id: str
    title: str
    status: str = "planned"
    stage: str | None = None
    complexity: str | None = None
    jira: str | None = None
    linear: str | None = None
    sprint: str | None = None
    branch: str | None = None
    worktree: str | None = None
    pr: str | None = None
    budget_estimate: int | None = None
    budget_actual: int = 0
    created: str = ""
    updated: str = ""
    blocked_on: str | None = None
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> "Card":
        meta, body = split_frontmatter(text)
        for key in ("id", "title", "status"):
            if not meta.get(key):
                raise CardParseError(f"missing required field: {key}")
        status = str(meta["status"])
        if status not in STATUSES:
            raise CardParseError(f"unknown status: {status!r}")
        stage = meta.get("stage")
        if stage is not None and stage not in STAGES:
            raise CardParseError(f"unknown stage: {stage!r}")
        budget = meta.get("budget") or {}
        if not isinstance(budget, dict):
            raise CardParseError(f"budget is not a mapping: {budget!r}")
        return cls(
            id=str(meta["id"]),
            title=str(meta["title"]),
            status=status,
            stage=stage,
            complexity=meta.get("complexity"),
            jira=meta.get("jira"),
            linear=meta.get("linear"),
            sprint=meta.get("sprint"),
            branch=meta.get("branch"),
            worktree=meta.get("worktree"),
            pr=meta.get("pr"),
            budget_estimate=parse_tokens(budget.get("estimate")),
            budget_actual=parse_tokens(budget.get("actual")) or 0,
            created=str(meta.get("created", "")),
            updated=str(meta.get("updated", "")),
            blocked_on=meta.get("blocked_on"),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "jira": self.jira,
            "linear": self.linear,
            "title": self.title,
            "status": self.status,
            "stage": self.stage,
            "complexity": self.complexity,
            "sprint": self.sprint,
            "branch": self.branch,
            "worktree": self.worktree,
            "pr": self.pr,
            "budget": {
                "estimate": format_tokens(self.budget_estimate),
                "actual": format_tokens(self.budget_actual),
            },
            "created": self.created,
            "updated": self.updated,
            "blocked_on": self.blocked_on,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"

    def set_stage(self, stage: str, now: str) -> None:
        if stage not in STAGES:
            raise CardParseError(f"unknown stage: {stage!r}")
        self.stage = stage
        self.status = "in-flight"
        self.blocked_on = None
        self.updated = now

    def block(self, reason: str, now: str) -> None:
        self.status = "blocked"
        self.blocked_on = reason
        self.updated = now

    def unblock(self, now: str) -> None:
        self.status = "in-flight" if self.stage else "planned"
        self.blocked_on = None
        self.updated = now

    def complete(self, now: str) -> None:
        self.status = "done"
        self.stage = None
        self.updated = now

    def abandon(self, now: str) -> None:
        self.status = "abandoned"
        self.stage = None
        self.updated = now

    def log_progress(self, note: str, tokens: int, now: str) -> None:
        self.budget_actual += tokens
        line = f"- {now} — {note} (~{format_tokens(tokens)} tokens)"
        self.body = append_to_section(self.body, "## Progress log", line)
        self.updated = now

    def log_review(self, stage: str, reviewers: int, verdict: str, now: str) -> None:
        round_no = self.review_rounds(stage) + 1
        block = f"### {stage} — round {round_no} ({reviewers} reviewers)\nVerdict: {verdict}"
        self.body = append_to_section(self.body, "## Review log", block)
        self.updated = now

    def review_rounds(self, stage: str) -> int:
        return self.body.count(f"### {stage} — round ")

    @property
    def tripwire_breached(self) -> bool:
        if self.budget_estimate is None:
            return False
        return self.budget_actual >= 2 * self.budget_estimate
