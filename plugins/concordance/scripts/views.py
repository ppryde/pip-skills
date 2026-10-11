"""A view: the file versions one worktree (or one base commit) sees, as path -> blob sha.

Clean tracked files use the index's blob sha; dirty and untracked files are hashed here the
way git hashes a blob, so a view never needs a commit. Base views come straight from git
objects, so the base never has to be checked out.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts import gitio

SUPPORTED = {".py": "python", ".ts": "typescript", ".tsx": "typescript",
             ".mts": "typescript", ".cts": "typescript"}


def lang_of(path: str) -> str | None:
    if path.endswith(".d.ts"):
        return None
    return SUPPORTED.get(PurePosixPath(path).suffix)


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@dataclass(frozen=True, eq=False)
class View:
    view_id: str
    kind: str  # wt | base
    root: Path
    ref: str | None
    files: dict[str, str]

    def read(self, paths: list[str]) -> dict[str, bytes]:
        if self.kind == "base":
            blobs = gitio.cat_blobs(self.root, [self.files[p] for p in paths])
            return {p: blobs[self.files[p]] for p in paths if self.files[p] in blobs}
        out: dict[str, bytes] = {}
        for p in paths:
            try:
                out[p] = (self.root / p).read_bytes()
            except OSError:
                continue
        return out

    def read_extra(self, path: str) -> bytes | None:
        if self.kind == "base":
            assert self.ref is not None
            return gitio.show_file(self.root, self.ref, path)
        try:
            return (self.root / path).read_bytes()
        except OSError:
            return None

    def text(self, path: str) -> str:
        return self.read([path]).get(path, b"").decode("utf-8", errors="replace")


def worktree_view_id(root: Path) -> str:
    return "wt-" + hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:12]


def worktree_view(cwd: Path) -> View:
    root = gitio.worktree_root(cwd)
    deleted = gitio.deleted_paths(root)
    files = {p: s for p, s in gitio.ls_files_stage(root).items()
             if p not in deleted and lang_of(p)}
    for p in gitio.changed_paths(root):
        if p in deleted or not lang_of(p):
            continue
        full = root / p
        if full.is_symlink() or not full.is_file():
            files.pop(p, None)
            continue
        try:
            files[p] = blob_sha(full.read_bytes())
        except OSError:  # unreadable or renamed away mid-scan: its index sha would be stale
            files.pop(p, None)
    return View(worktree_view_id(root), "wt", root, None, files)


def base_view(cwd: Path, commit: str) -> View:
    root = gitio.worktree_root(cwd)
    sha = gitio.rev_parse(root, commit)
    files = {p: s for p, s in gitio.ls_tree(root, sha).items() if lang_of(p)}
    return View(f"base-{sha}", "base", root, sha, files)
