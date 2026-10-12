"""Git plumbing for dispatch-prep and bootstrap: detect the repo's real base
branch (never assume ``main``), diff a worktree against it, add a worktree."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

FETCH_TIMEOUT = 60  # seconds: `worktree_add` fetches best-effort, then carries on
DIFF_TIMEOUT = 60  # seconds per git call while building a review diff
MAX_DIFF_BYTES = 200_000  # ~50k tokens: above this the reviewer gets stat + whole files up to the cap
LOCKFILES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "poetry.lock", "uv.lock", "Pipfile.lock", "pdm.lock", "Cargo.lock", "go.sum",
    "composer.lock", "Gemfile.lock", "mix.lock", "pubspec.lock", "Podfile.lock",
    "gradle.lockfile", "flake.lock",
})


class GitError(RuntimeError):
    """A git command overseer depends on failed."""


def _git(
    cwd: Path, *argv: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git without ever prompting (no stdin, no terminal credential
    prompt). ``timeout`` raises ``subprocess.TimeoutExpired`` for the caller."""
    return subprocess.run(
        ["git", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        timeout=timeout,
    )


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


def _diff_argv(worktree: Path) -> list[str]:
    base = base_ref(worktree)
    return ["diff", "HEAD"] if base == "HEAD" else ["diff", f"{base}...HEAD"]


def _run(worktree: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    try:
        return _git(worktree, *argv, timeout=DIFF_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {argv[0]} timed out after {DIFF_TIMEOUT}s") from exc


def diff_against_base(worktree: Path) -> str:
    result = _run(worktree, *_diff_argv(worktree))
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git diff failed")
    return result.stdout


@dataclass
class ReviewDiff:
    """The text written to ``diff.patch`` plus the one-line warnings behind its header."""

    text: str
    warnings: list[str] = field(default_factory=list)


def _dirty_files(worktree: Path) -> list[str]:
    result = _run(worktree, "status", "--porcelain", "--untracked-files=normal")
    if result.returncode != 0:
        return []
    return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]


def _classify(worktree: Path, argv: list[str]) -> list[tuple[str, int, str | None]]:
    """(path, changed lines, exclusion reason or None) per changed file, via --numstat."""
    result = _run(worktree, *argv[:1], "--numstat", "-z", *argv[1:])
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git diff --numstat failed")
    files: list[tuple[str, int, str | None]] = []
    records = result.stdout.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        added, _, rest = rec.partition("\t")
        deleted, _, path = rest.partition("\t")
        if path == "":  # a rename: the old and new paths follow as separate records
            i += 1
            path = records[i]
            i += 1
        if added == "-" and deleted == "-":
            files.append((path, 0, "binary"))
        else:
            reason = "lockfile" if path.rsplit("/", 1)[-1] in LOCKFILES else None
            files.append((path, int(added) + int(deleted), reason))
    return files


def review_diff(worktree: Path, *, max_bytes: int = MAX_DIFF_BYTES) -> ReviewDiff:
    """The branch-vs-base diff a reviewer reads, made safe to read.

    Lockfiles and binaries are left out (named in an ``# Excluded`` footer); a
    dirty worktree is flagged in a header, because uncommitted work is not in
    the diff; above ``max_bytes`` the diff degrades to ``--stat`` plus whole
    per-file hunks up to the cap, with the omitted files listed with the exact
    git command to read each. Every git call has ``DIFF_TIMEOUT``.
    """
    argv = _diff_argv(worktree)
    files = _classify(worktree, argv)
    excluded = [(p, why) for p, _, why in files if why]
    kept = [p for p, _, why in files if not why]
    warnings: list[str] = []
    # With no base branch the diff is `git diff HEAD`, which already shows tracked edits.
    dirty = _dirty_files(worktree) if argv != ["diff", "HEAD"] else []
    dirty_warning = ""
    if dirty:
        shown = ", ".join(dirty[:10]) + (f" and {len(dirty) - 10} more" if len(dirty) > 10 else "")
        dirty_warning = (
            f"worktree has {len(dirty)} uncommitted change(s) that are NOT in this diff: {shown}"
        )
        warnings.append(dirty_warning)
    body = ""
    if kept:
        excl = [f":(exclude,literal){p}" for p, _ in excluded]
        result = _run(worktree, *argv, "--", ".", *excl)
        if result.returncode != 0:
            raise GitError(result.stderr.strip() or "git diff failed")
        body = result.stdout
    if excluded:
        names = ", ".join(f"{p} ({why})" for p, why in excluded)
        warnings.append(f"{len(excluded)} file(s) excluded from the diff: {names}")
    notes_tail = ""
    if len(body.encode()) > max_bytes:
        body, omitted, stat = _cap(worktree, argv, kept, max_bytes)
        warnings.append(
            f"diff exceeds {max_bytes} bytes: whole-file hunks up to the cap, "
            f"{len(omitted)} file(s) omitted"
        )
        notes_tail += f"\n# Diff exceeds {max_bytes} bytes. Files changed:\n" + "".join(
            f"#   {line}\n" for line in stat.splitlines()
        )
        if omitted:
            cmd = " ".join(argv)
            notes_tail += "# Omitted (too large to include); read each with:\n" + "".join(
                f"#   git {cmd} -- {p}\n" for p in omitted
            )
    if excluded:
        notes_tail += "\n# Excluded from this diff (not reviewable text):\n" + "".join(
            f"#   {p} ({why})\n" for p, why in excluded
        )
    header = f"# WARNING: {dirty_warning}\n\n" if dirty_warning else ""
    return ReviewDiff(text=header + body + notes_tail, warnings=warnings)


def _cap(
    worktree: Path, argv: list[str], kept: list[str], max_bytes: int
) -> tuple[str, list[str], str]:
    """Whole per-file hunks, smallest first, until ``max_bytes`` is spent."""
    stat_run = _run(worktree, *argv[:1], "--stat", *argv[1:], "--", ".")
    stat = stat_run.stdout.strip() if stat_run.returncode == 0 else ""
    chunks: list[tuple[str, str]] = []
    for path in kept:
        res = _run(worktree, *argv, "--", path)
        if res.returncode == 0:
            chunks.append((path, res.stdout))
    chunks.sort(key=lambda c: len(c[1]))
    out, used, omitted = [], 0, []
    for path, text in chunks:
        size = len(text.encode())
        if used + size > max_bytes:
            omitted.append(path)
            continue
        out.append(text)
        used += size
    return "".join(out), omitted, stat


def worktree_add(repo: Path, path: Path, branch: str, start: str) -> None:
    """Create ``branch`` at ``start`` checked out in a new worktree at
    ``path``. Fetches first (best effort) so ``origin/<base>`` is current."""
    try:
        _git(repo, "fetch", "--quiet", "origin", timeout=FETCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass  # best effort: carry on with the refs we have
    result = _git(repo, "worktree", "add", "-b", branch, str(path), start)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git worktree add failed")
