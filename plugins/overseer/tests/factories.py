"""Shared test factories for overseer tests."""
import subprocess
from pathlib import Path

from scripts.models import Card


def make_card(card_id: str, **overrides: object) -> Card:
    fields = dict(
        id=card_id, title=f"T {card_id}", status="in-flight", stage="implementation",
        created="2026-07-08", updated="2026-07-08T10:00",
        body="## Review log\n\n## Progress log",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


def git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
