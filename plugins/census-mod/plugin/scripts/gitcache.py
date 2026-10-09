"""A per-worktree cache of git state, so a status line that refreshes every few
seconds runs no ``git`` at all on most refreshes.

One entry per worktree, one git pass (``status --porcelain=2 --branch -uno``; untracked files
are never listed, so never counted) fills
branch, uncommitted and ahead together. An entry is expired when it is older than
the TTL, or when the ``HEAD`` file's mtime changed (a checkout invalidates at
once, without a git call). Nothing here raises: git is best-effort.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TTL_ENV = "CENSUS_STATUSLINE_GIT_TTL"
DEFAULT_TTL_SECONDS = 15.0
GIT_TIMEOUT_SECONDS = 1
NEGATIVE_TTL_SECONDS = 60.0  # how long a failed git run (timeout, no git) is remembered
DIRNAME = "gitcache"
VERSION = 1


def ttl_seconds() -> float:
    """The configured TTL; ``0`` (or less) disables the cache."""
    raw = os.environ.get(TTL_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_TTL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TTL_SECONDS
    return max(0.0, value) if math.isfinite(value) else DEFAULT_TTL_SECONDS


def entry_path(cache_dir: Path, worktree: str) -> Path:
    digest = hashlib.sha256(worktree.encode("utf-8", "surrogateescape")).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def head_path(worktree: str) -> str | None:
    """The ``HEAD`` file for the repo containing ``worktree``, or None when it is
    not inside one. A linked worktree has ``.git`` as a file naming its gitdir."""
    here = Path(worktree)
    for folder in (here, *here.parents):
        dot_git = folder / ".git"
        try:
            if dot_git.is_dir():
                return str(dot_git / "HEAD")
            if dot_git.is_file():
                text = dot_git.read_text(errors="replace").strip()
                if text.startswith("gitdir:"):
                    gitdir = Path(text[len("gitdir:"):].strip())
                    if not gitdir.is_absolute():
                        gitdir = folder / gitdir
                    return str(gitdir / "HEAD")
                return None
        except OSError:
            return None
    return None


def _mtime(path: str | None) -> float | None:
    if not path:
        return None
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def parse_status(text: str) -> dict[str, Any]:
    """Fold ``git status --porcelain=2 --branch`` output into the entry fields."""
    head = oid = upstream = None
    ahead = 0
    uncommitted = 0
    for line in text.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):].strip()
        elif line.startswith("# branch.oid "):
            oid = line[len("# branch.oid "):].strip()
        elif line.startswith("# branch.upstream "):
            upstream = line[len("# branch.upstream "):].strip()
        elif line.startswith("# branch.ab "):
            for part in line.split()[2:]:
                if part.startswith("+") and part[1:].isdigit():
                    ahead = int(part[1:])
        elif line[:2] in ("1 ", "2 ", "u "):  # untracked (?) and ignored (!) do not count
            uncommitted += 1
    detached = head == "(detached)"
    unborn = oid == "(initial)"  # no commit yet: rev-parse had no branch to report, so neither do we
    if detached:
        branch = oid[:7] if oid and oid != "(initial)" else None
    else:
        branch = None if unborn else (head or None)
    return {
        "branch": branch,
        "detached": detached,
        "uncommitted": uncommitted,
        "ahead": ahead if upstream else 0,
        "has_upstream": bool(upstream),
    }


def _run_git(worktree: str) -> dict[str, Any] | None:
    """One git pass, or None on any failure (no git, not a repo, timeout)."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", worktree, "status", "--porcelain=2", "--branch", "-uno"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_status(result.stdout)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == VERSION else None


def _write(path: Path, entry: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".gitcache.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(entry, handle)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001, S110 - a cache that cannot be written is just a miss
        pass


def _fresh(entry: dict[str, Any], current_mtime: float | None, ttl: float, now: float) -> bool:
    if entry.get("failed"):
        ttl = NEGATIVE_TTL_SECONDS
    at = entry.get("at")
    if not isinstance(at, (int, float)) or not 0 <= now - at <= ttl:
        return False
    return entry.get("head_mtime") == current_mtime


_EMPTY: dict[str, Any] = {
    "branch": None,
    "detached": False,
    "uncommitted": 0,
    "ahead": 0,
    "has_upstream": False,
}


def lookup(cache_dir: Path, worktree: str | None, now: float | None = None) -> dict[str, Any]:
    """Git state for ``worktree`` — always a dict with the entry fields; a
    non-repo, a missing git or a failed run gives branch None.

    A warm call reads one small file and runs no git. A timeout keeps the last
    cached value (and re-stamps it so a slow git is not retried every refresh).
    """
    if not worktree:
        return dict(_EMPTY)
    try:
        return _lookup(cache_dir, worktree, time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - never break the status line over git
        return dict(_EMPTY)


def _lookup(cache_dir: Path, worktree: str, now: float) -> dict[str, Any]:
    ttl = ttl_seconds()
    head = head_path(worktree)
    mtime = _mtime(head)
    path = entry_path(cache_dir, worktree)
    cached = _read(path) if ttl > 0 else None
    if cached is not None and _fresh(cached, mtime, ttl, now):
        return cached
    state: dict[str, Any] | None
    if head is None:  # not inside a repo: skip git, remember the answer
        state = dict(_EMPTY)
    else:
        state = _run_git(worktree)
        if state is None:
            if cached is None:  # remember the failure briefly so a slow repo is not retried every refresh
                if ttl > 0:
                    _write(path, {"version": VERSION, "worktree": worktree, "head_path": head,
                                  "head_mtime": mtime, **_EMPTY, "failed": True, "at": now})
                return dict(_EMPTY)
            state = {k: cached.get(k, v) for k, v in _EMPTY.items()}
            if cached.get("failed"):  # still failing: keep the long backoff
                state["failed"] = True
    entry = {
        "version": VERSION,
        "worktree": worktree,
        "head_path": head,
        "head_mtime": mtime,
        **state,
        "at": now,
    }
    if ttl > 0:
        _write(path, entry)
    return entry


def prune(cache_dir: Path, max_age_seconds: float, now: float | None = None) -> None:
    """Delete entries not touched for ``max_age_seconds`` (by mtime). Never raises."""
    wall = time.time() if now is None else now
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return
    for name in names:
        path = cache_dir / name
        try:
            if wall - path.stat().st_mtime > max_age_seconds:
                path.unlink()
        except OSError:
            pass
