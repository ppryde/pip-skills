"""Knowledge base: Fact parse/serialise, staleness, store ops, index."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from scripts.models import CardParseError, split_frontmatter
from scripts.store import _uniquify, slugify, state_root

FACT_STATUSES = {"active", "stale", "retired"}
STALE_DAYS = 90
_MINTED_FACT_RE = re.compile(r"\AKB-(\d+)-")


class FactParseError(ValueError):
    """A fact file that cannot be parsed or fails validation."""


def is_stale(verified: str, today: str, max_age_days: int = STALE_DAYS) -> bool:
    if not verified:
        return False
    try:
        v = datetime.strptime(verified[:10], "%Y-%m-%d")
        t = datetime.strptime(today[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return (t - v).days > max_age_days


@dataclass
class Fact:
    """One falsifiable statement with provenance and a verification date."""

    id: str
    statement: str
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    created: str = ""
    verified: str = ""
    status: str = "active"
    superseded_by: str | None = None
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> Fact:
        try:
            meta, body = split_frontmatter(text)
        except CardParseError as exc:
            raise FactParseError(str(exc)) from exc
        for key in ("id", "statement"):
            if not meta.get(key):
                raise FactParseError(f"missing required field: {key}")
        status = str(meta.get("status", "active"))
        if status not in FACT_STATUSES:
            raise FactParseError(f"unknown status: {status!r}")
        tags_raw = meta.get("tags")
        if isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        elif tags_raw:
            tags = [str(tags_raw)]
        else:
            tags = []
        return cls(
            id=str(meta["id"]),
            statement=str(meta["statement"]),
            tags=tags,
            source=meta.get("source"),
            created=str(meta.get("created", "")),
            verified=str(meta.get("verified", "")),
            status=status,
            superseded_by=meta.get("superseded_by"),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "statement": self.statement,
            "tags": self.tags or None,
            "source": self.source,
            "created": self.created,
            "verified": self.verified,
            "status": self.status,
            "superseded_by": self.superseded_by,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"

    def effective_status(self, today: str) -> str:
        if self.status == "active" and is_stale(self.verified, today):
            return "stale"
        return self.status


def knowledge_root(repo_root: Path) -> Path:
    return state_root(repo_root) / "knowledge"


def ensure_kb(kb: Path) -> None:
    for sub in ("facts", "retired", "corrupt"):
        (kb / sub).mkdir(parents=True, exist_ok=True)


def mint_fact_id(kb: Path) -> str:
    highest = 0
    for directory in (kb / "facts", kb / "retired"):
        for path in directory.glob("KB-*.md"):
            match = _MINTED_FACT_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"KB-{highest + 1:03d}"


def fact_path(kb: Path, fact: Fact) -> Path:
    return kb / "facts" / f"{fact.id}-{slugify(fact.statement)}.md"


def find_fact_path(kb: Path, fact_id: str) -> Path:
    matches = sorted((kb / "facts").glob(f"{fact_id}-*.md"))
    if not matches:
        raise FileNotFoundError(f"no live fact with id {fact_id}")
    return matches[0]


def load_fact(path: Path) -> Fact:
    try:
        return Fact.from_text(path.read_text())
    except FactParseError as exc:
        raise FactParseError(f"{path.name}: {exc}") from exc


def save_fact(kb: Path, fact: Fact) -> Path:
    path = fact_path(kb, fact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fact.to_text())
    return path


def quarantine_fact(kb: Path, path: Path) -> Path:
    target = _uniquify(kb / "corrupt" / path.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)
    return target


def load_facts(kb: Path) -> tuple[list[Fact], list[Path]]:
    facts: list[Fact] = []
    quarantined: list[Path] = []
    for path in sorted((kb / "facts").glob("*.md")):
        try:
            facts.append(load_fact(path))
        except FactParseError:
            quarantined.append(quarantine_fact(kb, path))
    facts.sort(key=lambda f: f.id)
    return facts, quarantined


def load_retired(kb: Path) -> list[Fact]:
    facts = []
    for path in (kb / "retired").glob("*.md"):
        try:
            facts.append(Fact.from_text(path.read_text()))
        except FactParseError:
            continue
    return sorted(facts, key=lambda f: f.id)


def retire_fact_file(kb: Path, fact: Fact) -> Path:
    target = _uniquify(kb / "retired" / f"{fact.id}-{slugify(fact.statement)}.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(fact.to_text())
    live = fact_path(kb, fact)
    if live.exists():
        live.unlink()
    return target


def generate_knowledge_index(
    facts: list[Fact], retired: list[Fact], now: str
) -> str:
    active = [f for f in facts if f.status == "active"]
    stale = [f for f in facts if f.status == "stale"]

    lines = [f"# Knowledge — {len(active)} active", f"Updated: {now}", ""]
    lines.append("## Active")
    if active:
        lines += ["| Fact | Statement | Tags | Verified |", "|---|---|---|---|"]
        for f in active:
            tags = ", ".join(f.tags) or "—"
            lines.append(f"| {f.id} | {f.statement} | {tags} | {f.verified or '?'} |")
    else:
        lines.append("_No active facts._")

    lines += ["", "## Stale — verify before trusting"]
    if stale:
        for f in stale:
            tags = ", ".join(f.tags) or "—"
            lines.append(f"- {f.id} — {f.statement} ({tags}, last verified {f.verified or '?'})")
    else:
        lines.append("_None._")

    lines += ["", f"## Retired: {len(retired)}",
              "See `retired/` for superseded and refuted facts."]
    return "\n".join(lines) + "\n"


def rebuild_knowledge_index(repo_root: Path, today: str) -> list[Path]:
    kb = knowledge_root(repo_root)
    ensure_kb(kb)
    facts, quarantined = load_facts(kb)
    for fact in facts:
        effective = fact.effective_status(today)
        if effective != fact.status:
            fact.status = effective
            save_fact(kb, fact)
    retired = load_retired(kb)
    (kb / "knowledge.md").write_text(generate_knowledge_index(facts, retired, today))
    return quarantined
