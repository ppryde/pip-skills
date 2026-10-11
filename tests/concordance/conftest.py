"""Shared fixtures. Every test runs against a throwaway git repo and a store in tmp_path."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Never touch the real account store (repo rule, CLAUDE.md "Test isolation"):
    # an unpinned run would write index.db under the developer's real config dir.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("CONCORDANCE_DB", raising=False)
    monkeypatch.delenv("CONCORDANCE_USAGE_DB", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    # Keep user git config (hooks, templates, signing) out of fixture repos.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        ).stdout

    def write(self, files: dict[str, str | None]) -> None:
        for rel, text in files.items():
            path = self.root / rel
            if text is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def commit(self, msg: str = "c") -> str:
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def worktree(self, name: str, branch: str) -> Repo:
        path = self.root.parent / name
        self.git("worktree", "add", "-q", "-b", branch, str(path))
        return Repo(path)


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Repo]:
    def _make(files: dict[str, str], name: str = "repo") -> Repo:
        root = tmp_path / name
        root.mkdir()
        repo = Repo(root)
        repo.git("init", "-q", "-b", "main")
        repo.write(dict(files))
        repo.commit("base")
        return repo

    return _make
