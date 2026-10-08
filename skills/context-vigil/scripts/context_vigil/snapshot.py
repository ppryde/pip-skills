"""Generic, tool-agnostic session snapshot — vigil's default handover content.

Pointer-only: counts and refs, never file names. Best-effort: git calls
degrade gracefully (a non-git dir yields the cwd line only), and nothing here
ever raises. Mirrors resume.py's subprocess pattern.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_TIMEOUT = 5  # seconds per git call; a hung repo degrades to the cwd line


class _Git:
    """One snapshot's git calls. The first timeout or missing binary ends them all,
    so a repo that hangs costs one timeout, not one per call."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.dead = False

    def __call__(self, *args: str, strip: bool = True) -> str | None:
        if self.dead:
            return None
        try:
            result = subprocess.run(
                ["git", *args], cwd=self.cwd, capture_output=True, text=True,
                timeout=_GIT_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            self.dead = True
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() if strip else result.stdout


def _short(git: _Git, ref: str) -> str | None:
    return git("rev-parse", "--short", ref)


def _default_base(git: _Git) -> str | None:
    """The default remote branch (origin/HEAD), else the first common name that exists."""
    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    candidates = ([head] if head else []) + [
        "origin/main", "origin/master", "main", "master"]
    for ref in candidates:
        if git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None:
            return ref
    return None


def _counts(git: _Git) -> tuple[int, int, int]:
    """(modified, staged, untracked) from porcelain status; a file can be two of them."""
    modified = staged = untracked = 0
    for line in (git("status", "--porcelain", strip=False) or "").splitlines():
        if line.startswith("??"):
            untracked += 1
            continue
        if line[:1] not in (" ", "?", ""):
            staged += 1
        if line[1:2] not in (" ", "?", ""):
            modified += 1
    return modified, staged, untracked


def session_snapshot(cwd: Path) -> str:
    """A fixed-size pointer block: where things stand and how to get detail.

    Never lists files — the commands at the end do that on demand.
    """
    git = _Git(cwd)
    lines = ["## Session snapshot", "", f"- Working directory: `{cwd}`"]
    if git("rev-parse", "--is-inside-work-tree") != "true":
        return "\n".join(lines) + "\n"
    branch = git("symbolic-ref", "--short", "HEAD") or "(detached)"
    if git.dead:                  # git hung: degrade to the cwd line
        return "\n".join(lines) + "\n"
    head = _short(git, "HEAD")
    lines += ["", "## Git", "",
              f"- Branch: `{branch}`" + (f" @ {head}" if head else " (no commits yet)")]
    base = _default_base(git) if head else None
    base_sha = git("merge-base", "HEAD", base) if base else None
    if base and base_sha:
        lines.append(f"- Base: `{base}` @ {_short(git, base_sha) or base_sha[:7]}")
    modified, staged, untracked = _counts(git)
    lines.append(f"- Working tree: {modified} modified, {staged} staged, "
                 f"{untracked} untracked")
    diffstat = f"git diff --stat {base}...HEAD" if base and base_sha else None
    commands = ["git status --short"] + ([diffstat] if diffstat else []) + ["git diff"]
    lines.append("- Detail: " + " · ".join(f"`{c}`" for c in commands))
    return "\n".join(lines) + "\n"
