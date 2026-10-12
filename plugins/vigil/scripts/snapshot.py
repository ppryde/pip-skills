"""Generic, tool-agnostic session snapshot — vigil's default handover content.

Best-effort: git calls degrade gracefully (a non-git dir yields the cwd line
only), and nothing here ever raises. Mirrors resume.py's subprocess pattern.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


MAX_STATUS_LINES = 40


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _recent_tracked(cwd: Path, limit: int) -> list[str]:
    listing = _git(cwd, "ls-files")
    if not listing:
        return []
    files = [f for f in listing.splitlines() if f]
    paired: list[tuple[float, str]] = []
    for f in files:
        try:
            mtime = (cwd / f).stat().st_mtime
        except OSError:
            continue
        paired.append((mtime, f))
    paired.sort(reverse=True)
    return [f for _, f in paired[:limit]]


def session_snapshot(cwd: Path, limit: int = 10) -> str:
    lines = ["## Session snapshot", "", f"- Working directory: `{cwd}`"]
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(cwd, "status", "--short")
    if branch is not None:
        lines += ["", "## Git", "", f"- Branch: `{branch}`"]
        if status:
            status_lines = status.splitlines()
            if len(status_lines) > MAX_STATUS_LINES:
                extra = len(status_lines) - MAX_STATUS_LINES
                status_lines = status_lines[:MAX_STATUS_LINES]
                status_lines.append(f"... {extra} more")
            lines += ["- Status:", "", "```", "\n".join(status_lines), "```"]
        else:
            lines.append("- Status: clean")
        recent = _recent_tracked(cwd, limit)
        if recent:
            lines += ["", "## Recently modified", ""]
            lines += [f"- `{f}`" for f in recent]
    return "\n".join(lines) + "\n"
