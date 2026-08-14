"""Discover the two reviewer sources and the strategy set from disk.

Discovery is dynamic: dropping a new `strategies/<name>.md` or
`reviewers/<name>.md` makes it available with no code change. Files whose
basename starts with '_' (e.g. _template.md) are authoring templates and
are excluded."""
from __future__ import annotations

import os
from pathlib import Path


def _stems(directory: Path) -> list[str]:
    if not Path(directory).is_dir():
        return []
    return sorted(
        p.stem for p in Path(directory).glob("*.md")
        if not p.name.startswith("_")
    )


def discover_strategies(strategies_dir: Path) -> list[str]:
    return _stems(strategies_dir)


def discover_builtin_reviewers(reviewers_dir: Path) -> list[str]:
    return _stems(reviewers_dir)


def review_clone_root() -> Path:
    """Resolve the review-clone persona root, matching review-clone's own
    resolution: REVIEW_CLONE_ROOT, else $CLAUDE_CONFIG_DIR/review-clone,
    else ~/.claude/review-clone."""
    env = os.environ.get("REVIEW_CLONE_ROOT")
    if env:
        return Path(env)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg:
        return Path(cfg) / "review-clone"
    return Path.home() / ".claude" / "review-clone"


def discover_clone_personas() -> list[str]:
    root = review_clone_root()
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and (p / "PERSONA.md").exists()
    )


def available_reviewers(reviewers_dir: Path) -> list[str]:
    return discover_builtin_reviewers(reviewers_dir) + [
        f"clone:{a}" for a in discover_clone_personas()
    ]
