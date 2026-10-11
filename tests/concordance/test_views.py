import os

from scripts import gitio
from scripts.views import base_view, blob_sha, lang_of, worktree_view, worktree_view_id


def test_lang_of() -> None:
    assert lang_of("a/b.py") == "python"
    assert lang_of("x.tsx") == "typescript"
    assert lang_of("types.d.ts") is None
    assert lang_of("README.md") is None


def test_blob_sha_matches_git(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    assert blob_sha(b"x = 1\n") == repo.git("hash-object", "a.py").strip()


def test_worktree_view_sees_dirty_untracked_and_skips_deleted(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n", "c.py": "z = 1\n", "R.md": "r"})
    repo.write({"a.py": "x = 2\n", "new.py": "n = 1\n", "c.py": None})
    v = worktree_view(repo.root)
    assert set(v.files) == {"a.py", "b.py", "new.py"}
    assert v.files["a.py"] == blob_sha(b"x = 2\n")
    assert v.read(["a.py", "b.py"]) == {"a.py": b"x = 2\n", "b.py": b"y = 1\n"}
    assert v.kind == "wt" and v.ref is None


def test_base_view_reads_from_git_without_checkout(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "tsconfig.json": "{}"})
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"a.py": "x = 2\n"})
    repo.commit("second")
    v = base_view(repo.root, sha)
    assert v.view_id == f"base-{sha}" and v.ref == sha
    assert v.read(["a.py"]) == {"a.py": b"x = 1\n"}
    assert v.read_extra("tsconfig.json") == b"{}"


def test_view_ids_are_stable_per_worktree_and_distinct_between_them(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    wt = repo.worktree("wt1", "feat")
    assert worktree_view(repo.root).view_id == worktree_view_id(repo.root)
    assert worktree_view(repo.root / ".").view_id == worktree_view(repo.root).view_id
    assert worktree_view(wt.root).view_id != worktree_view(repo.root).view_id


def test_subdirectory_cwd_resolves_to_the_worktree_root(make_repo) -> None:
    repo = make_repo({"pkg/a.py": "x = 1\n"})
    v = worktree_view(repo.root / "pkg")
    assert v.root == gitio.worktree_root(repo.root) and "pkg/a.py" in v.files


def test_symlinks_are_skipped(make_repo) -> None:  # Review Focus 5
    repo = make_repo({"a.py": "x = 1\n"})
    os.symlink("a.py", repo.root / "link.py")
    repo.commit("tracked link")
    os.symlink("a.py", repo.root / "untracked_link.py")
    assert set(worktree_view(repo.root).files) == {"a.py"}
    sha = repo.git("rev-parse", "HEAD").strip()
    assert set(base_view(repo.root, sha).files) == {"a.py"}
