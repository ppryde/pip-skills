"""Generic, tool-agnostic session snapshot — vigil's default handover content.

Pointer-only: counts and refs, never file names. Best-effort: git calls
degrade gracefully (a non-git dir yields the cwd line only), and nothing here
ever raises. Mirrors resume.py's subprocess pattern.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_TIMEOUT = 5  # seconds per git call; a hung repo degrades to the cwd line


def _git(cwd: Path, *args: str, strip: bool = True) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() if strip else result.stdout


def _short(cwd: Path, ref: str) -> str | None:
    return _git(cwd, "rev-parse", "--short", ref)


def _default_base(cwd: Path) -> str | None:
    """The default remote branch (origin/HEAD), else the first common name that exists."""
    head = _git(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    candidates = ([head] if head else []) + [
        "origin/main", "origin/master", "main", "master"]
    for ref in candidates:
        if _git(cwd, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None:
            return ref
    return None


def _counts(cwd: Path) -> tuple[int, int, int]:
    """(modified, staged, untracked) from porcelain status; a file can be two of them."""
    modified = staged = untracked = 0
    for line in (_git(cwd, "status", "--porcelain", strip=False) or "").splitlines():
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
    lines = ["## Session snapshot", "", f"- Working directory: `{cwd}`"]
    if _git(cwd, "rev-parse", "--is-inside-work-tree") != "true":
        return "\n".join(lines) + "\n"
    branch = _git(cwd, "symbolic-ref", "--short", "HEAD") or "(detached)"
    head = _short(cwd, "HEAD")
    lines += ["", "## Git", "",
              f"- Branch: `{branch}`" + (f" @ {head}" if head else " (no commits yet)")]
    base = _default_base(cwd) if head else None
    base_sha = _git(cwd, "merge-base", "HEAD", base) if base else None
    if base and base_sha:
        lines.append(f"- Base: `{base}` @ {_short(cwd, base_sha) or base_sha[:7]}")
    modified, staged, untracked = _counts(cwd)
    lines.append(f"- Working tree: {modified} modified, {staged} staged, "
                 f"{untracked} untracked")
    diffstat = f"git diff --stat {base}...HEAD" if base and base_sha else None
    commands = ["git status --short"] + ([diffstat] if diffstat else []) + ["git diff"]
    lines.append("- Detail: " + " · ".join(f"`{c}`" for c in commands))
    return "\n".join(lines) + "\n"
