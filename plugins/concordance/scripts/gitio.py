"""Every git call concordance makes. Argv only (no shell); listings use -z so any path survives."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_SKIP_MODES = {b"120000", b"160000"}  # symlinks and submodules are never indexed


class GitError(RuntimeError):
    pass


def git(cwd: Path, *args: str, input: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", "-C", str(cwd), *args], input=input, capture_output=True,
                          check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise GitError(f"git {' '.join(args)}: {err}")
    return proc.stdout


def git_text(cwd: Path, *args: str) -> str:
    return os.fsdecode(git(cwd, *args))


def worktree_root(cwd: Path) -> Path:
    return Path(git_text(cwd, "rev-parse", "--show-toplevel").strip()).resolve()


def common_dir(cwd: Path) -> Path:
    out = git_text(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(out).resolve()


def default_branch(cwd: Path) -> str:
    try:
        ref = git_text(cwd, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
        return ref.removeprefix("refs/remotes/")
    except GitError:
        pass
    for candidate in ("main", "master"):
        try:
            git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}")
            return candidate
        except GitError:
            continue
    raise GitError("no default branch found (origin/HEAD, main, master); pass --base <ref>")


def merge_base(cwd: Path, a: str, b: str = "HEAD") -> str:
    return git_text(cwd, "merge-base", a, b).strip()


def rev_parse(cwd: Path, ref: str) -> str:
    return git_text(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def _split_z(out: bytes) -> list[bytes]:
    return [entry for entry in out.split(b"\0") if entry]


NON_UTF8 = "non-UTF-8 path"


def _path(raw: bytes, skipped: dict[str, str] | None = None) -> str | None:
    """A path as text, or None when it is not valid UTF-8: such a file cannot be stored, so it
    is not indexed. It is recorded (escaped, with the reason) in `skipped` for the footer."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        if skipped is not None:
            skipped[raw.decode("utf-8", "backslashreplace")] = NON_UTF8
        return None


def ls_files_stage(cwd: Path, skipped: dict[str, str] | None = None) -> dict[str, str]:
    """Tracked files -> index blob sha (symlinks and submodules skipped)."""
    result: dict[str, str] = {}
    for entry in _split_z(git(cwd, "ls-files", "-s", "-z")):
        meta, path = entry.split(b"\t", 1)
        mode, sha, _stage = meta.split()
        if mode in _SKIP_MODES:
            continue
        name = _path(path, skipped)
        if name is not None:
            result[name] = sha.decode()
    return result


def changed_paths(cwd: Path, skipped: dict[str, str] | None = None) -> list[str]:
    """Paths whose working-tree content differs from the index, plus untracked non-ignored files."""
    modified = _split_z(git(cwd, "diff", "--name-only", "-z"))
    untracked = _split_z(git(cwd, "ls-files", "-o", "--exclude-standard", "-z"))
    return [n for p in [*modified, *untracked] if (n := _path(p, skipped)) is not None]


def deleted_paths(cwd: Path) -> set[str]:
    return {n for p in _split_z(git(cwd, "ls-files", "-d", "-z")) if (n := _path(p)) is not None}


def ls_tree(cwd: Path, commit: str, skipped: dict[str, str] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in _split_z(git(cwd, "ls-tree", "-r", "-z", commit)):
        meta, path = entry.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind != b"blob" or mode in _SKIP_MODES:
            continue
        name = _path(path, skipped)
        if name is not None:
            result[name] = sha.decode()
    return result


def cat_blobs(cwd: Path, shas: list[str]) -> dict[str, bytes]:
    if not shas:
        return {}
    out = git(cwd, "cat-file", "--batch", input=("\n".join(shas) + "\n").encode())
    result: dict[str, bytes] = {}
    pos = 0
    for sha in shas:
        newline = out.index(b"\n", pos)
        header = out[pos:newline].split()
        if len(header) < 3 or header[1] == b"missing":
            pos = newline + 1
            continue
        size = int(header[2])
        start = newline + 1
        result[sha] = out[start : start + size]
        pos = start + size + 1
    return result


def show_file(cwd: Path, commit: str, path: str) -> bytes | None:
    try:
        return git(cwd, "show", f"{commit}:{path}")
    except GitError:
        return None


def live_worktrees(cwd: Path) -> set[str]:
    out = git_text(cwd, "worktree", "list", "--porcelain")
    return {
        str(Path(line.removeprefix("worktree ")).resolve())
        for line in out.splitlines()
        if line.startswith("worktree ")
    }
