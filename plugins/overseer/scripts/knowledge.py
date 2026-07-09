"""Knowledge base: Fact parse/serialise, staleness, store ops, index."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import yaml

from scripts.models import split_frontmatter

FACT_STATUSES = {"active", "stale", "retired"}
STALE_DAYS = 90


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
        meta, body = split_frontmatter(text)
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
