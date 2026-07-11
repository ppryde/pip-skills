"""Filesystem root for vigil state — repo-local `.vigil/`, keyed by cwd."""
from __future__ import annotations

from pathlib import Path

VIGIL_DIRNAME = ".vigil"


def vigil_root(repo_root: Path) -> Path:
    return repo_root / VIGIL_DIRNAME


def ensure_root(repo_root: Path) -> Path:
    """Create `.vigil/` and git-ignore it (idempotent). Returns the root."""
    root = vigil_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if f"{VIGIL_DIRNAME}/" not in existing.split("\n"):
        suffix = "" if existing in ("", "\n") or existing.endswith("\n") else "\n"
        gitignore.write_text(f"{existing}{suffix}{VIGIL_DIRNAME}/\n")
    return root


def _uniquify(target: Path) -> Path:
    """If target exists, append a numeric suffix ({stem}.1{suffix}, .2, …) until free."""
    original = target
    counter = 0
    while target.exists():
        counter += 1
        target = original.parent / f"{original.stem}.{counter}{original.suffix}"
    return target
