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


def _config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", "") or Path.home() / ".claude")


def review_clone_root() -> Path:
    """Resolve the review-clone persona root, matching review-clone's own resolution (its RA-8 storage):
    REVIEW_CLONE_ROOT, else <config dir>/review-clone/personas, where <config dir> is CLAUDE_CONFIG_DIR or ~/.claude."""
    env = os.environ.get("REVIEW_CLONE_ROOT")
    if env:
        return Path(env)
    return _config_dir() / "review-clone" / "personas"


def review_clone_legacy_roots() -> list[Path]:
    """Personas written before RA-8 sit directly under <config dir>/review-clone/<alias>; read-only fallback,
    never active when REVIEW_CLONE_ROOT overrides the root."""
    if os.environ.get("REVIEW_CLONE_ROOT"):
        return []
    return [_config_dir() / "review-clone"]


def review_clone_roots() -> list[Path]:
    """The persona roots in lookup order: the current root, then the legacy one."""
    return [review_clone_root(), *review_clone_legacy_roots()]


def discover_clone_personas() -> list[str]:
    found: set[str] = set()
    for root in review_clone_roots():
        if root.is_dir():
            found |= {p.name for p in root.iterdir() if p.is_dir() and (p / "PERSONA.md").exists()}
    return sorted(found)


def available_reviewers(reviewers_dir: Path) -> list[str]:
    return discover_builtin_reviewers(reviewers_dir) + [
        f"clone:{a}" for a in discover_clone_personas()
    ]
