"""Git plumbing for dispatch-prep and bootstrap: detect the repo's real base
branch (never assume ``main``), diff a worktree against it, add a worktree."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git command overseer depends on failed."""


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)


def base_ref(repo: Path) -> str:
    """``origin/HEAD``'s target (e.g. ``origin/main``), else a local
    ``main``/``master``, else ``HEAD``."""
    head = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip()
    for candidate in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", candidate).returncode == 0:
            return candidate
    return "HEAD"


def diff_against_base(worktree: Path) -> str:
    base = base_ref(worktree)
    argv = ["diff", "HEAD"] if base == "HEAD" else ["diff", f"{base}...HEAD"]
    result = _git(worktree, *argv)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git diff failed")
    return result.stdout


def worktree_add(repo: Path, path: Path, branch: str, start: str) -> None:
    """Create ``branch`` at ``start`` checked out in a new worktree at
    ``path``. Fetches first (best effort) so ``origin/<base>`` is current."""
    _git(repo, "fetch", "--quiet", "origin")
    result = _git(repo, "worktree", "add", "-b", branch, str(path), start)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git worktree add failed")
