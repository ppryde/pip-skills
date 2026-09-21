"""Filesystem root for vigil state — repo-local `.claude/vigil/`, keyed by cwd."""
from __future__ import annotations

from pathlib import Path

CLAUDE_DIRNAME = ".claude"
VIGIL_DIRNAME = "vigil"


def vigil_root(repo_root: Path) -> Path:
    return repo_root / CLAUDE_DIRNAME / VIGIL_DIRNAME


def ensure_root(repo_root: Path) -> Path:
    """Create `.claude/vigil/` with a self-contained `.gitignore` (idempotent).

    The `.gitignore` lives inside `.claude/vigil/` itself (`*`, same pattern as
    a tool cache dir) so vigil never has to edit the repo's own top-level
    `.gitignore` — no diff lands in a consuming repo just from vigil running.
    Returns the root.
    """
    root = vigil_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return root


def _uniquify(target: Path) -> Path:
    """If target exists, append a numeric suffix ({stem}.1{suffix}, .2, …) until free."""
    original = target
    counter = 0
    while target.exists():
        counter += 1
        target = original.parent / f"{original.stem}.{counter}{original.suffix}"
    return target
