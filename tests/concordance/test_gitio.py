from pathlib import Path

import pytest

from scripts import gitio, paths


def test_store_path_roots_at_config_dir(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    store = paths.store_path(gitio.common_dir(repo.root))
    assert store.is_relative_to(tmp_path / "config" / "concordance")
    assert store.name == "index.db"
    assert store.parent.name.startswith("repo-")


def test_store_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_repo) -> None:
    monkeypatch.setenv("CONCORDANCE_DB", str(tmp_path / "x.db"))
    repo = make_repo({"a.py": "x = 1\n"})
    assert paths.store_path(gitio.common_dir(repo.root)) == tmp_path / "x.db"


def test_worktrees_share_a_repo_key(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    wt = repo.worktree("wt1", "feat")
    assert gitio.common_dir(repo.root) == gitio.common_dir(wt.root)
    assert gitio.worktree_root(wt.root / ".") == wt.root.resolve()


def test_default_branch_falls_back_to_main(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    assert gitio.default_branch(repo.root) == "main"


def test_ls_files_handles_spaces_and_unicode(make_repo) -> None:  # Review Focus 3
    repo = make_repo({"dir with space/ünï.py": "x = 1\n"})
    assert "dir with space/ünï.py" in gitio.ls_files_stage(repo.root)


def test_changed_deleted_and_untracked(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
    repo.write({"a.py": "x = 2\n", "new.py": "n = 1\n", "b.py": None})
    assert set(gitio.changed_paths(repo.root)) == {"a.py", "new.py", "b.py"}
    assert gitio.deleted_paths(repo.root) == {"b.py"}


def test_ls_tree_and_cat_blobs_read_a_commit_without_checkout(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"a.py": "x = 99\n"})
    tree = gitio.ls_tree(repo.root, sha)
    assert set(tree) == {"a.py", "pkg/b.py"}
    blobs = gitio.cat_blobs(repo.root, [tree["a.py"], tree["pkg/b.py"]])
    assert blobs[tree["a.py"]] == b"x = 1\n"
    assert gitio.show_file(repo.root, sha, "a.py") == b"x = 1\n"
    assert gitio.show_file(repo.root, sha, "missing.json") is None


def test_live_worktrees_lists_resolved_paths(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    wt = repo.worktree("wt1", "feat")
    live = gitio.live_worktrees(repo.root)
    assert str(repo.root.resolve()) in live and str(wt.root.resolve()) in live


def test_git_error_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(gitio.GitError, match="rev-parse"):
        gitio.worktree_root(tmp_path)


def test_non_utf8_paths_are_skipped_in_every_listing(tmp_path: Path, make_repo) -> None:
    import subprocess
    repo = make_repo({"ok.py": "x = 1\n"})
    blob = repo.git("hash-object", "-w", "ok.py").strip()
    info = f"100644 {blob}\t".encode() + b"app/bad\xff.py\n"
    subprocess.run(["git", "-C", str(repo.root), "update-index", "--add", "--index-info"],
                   input=info, check=True)
    assert gitio.ls_files_stage(repo.root) == {"ok.py": blob}
    repo.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "bad")
    assert gitio.ls_tree(repo.root, "HEAD") == {"ok.py": blob}
    assert gitio.changed_paths(repo.root) == []
    assert gitio.deleted_paths(repo.root) == set()


def test_non_utf8_paths_in_the_modified_and_untracked_branches(
        make_repo, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo({"ok.py": "x = 1\n"})
    real = gitio.git

    def fake(cwd: Path, *args: str, input: bytes | None = None) -> bytes:
        if args[:2] == ("diff", "--name-only"):
            return b"ok.py\0mod\xff.py\0"
        if args[:2] == ("ls-files", "-o"):
            return b"new\xfe.py\0new.py\0"
        return real(cwd, *args, input=input)

    monkeypatch.setattr(gitio, "git", fake)
    skipped: dict[str, str] = {}
    assert gitio.changed_paths(repo.root, skipped) == ["ok.py", "new.py"]
    assert skipped == {"mod\\xff.py": "non-UTF-8 path", "new\\xfe.py": "non-UTF-8 path"}
