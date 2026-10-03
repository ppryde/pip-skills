from __future__ import annotations

from pathlib import Path

import pytest
from context_vigil import paths


def test_data_root_honours_override(iso: Path) -> None:
    assert paths.data_root() == iso / "data"


def test_data_root_defaults_under_config_dir(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_VIGIL_HOME")
    assert paths.data_root() == iso / "claude" / "context-vigil"


def test_config_dir_defaults_to_home_dot_claude(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert paths.config_dir() == iso / "home" / ".claude"


def test_worktree_slug_is_filesystem_safe_and_stable(repo: Path) -> None:
    slug = paths.worktree_slug(repo)
    assert "/" not in slug and slug == paths.worktree_slug(repo / ".")


def test_worktree_key_resolves_symlinks(repo: Path, iso: Path) -> None:
    link = iso / "link"
    link.symlink_to(repo)
    assert paths.worktree_key(link) == paths.worktree_key(repo)


def test_scope_dir_is_worktree_dir_without_session(repo: Path) -> None:
    assert paths.scope_dir(repo) == paths.worktree_dir(repo)


def test_scope_dir_uses_env_session(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-2")
    assert paths.scope_dir(repo) == paths.worktree_dir(repo) / "sessions" / "cc-repo-2"


def test_scope_dir_falls_back_to_tmux_pane(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "/private/tmp/tmux-501/default,123,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    assert paths.scope_dir(repo).name == "tmux-default-7"


def test_explicit_session_beats_pane(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "/private/tmp/tmux-501/default,123,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-1")
    assert paths.scope_dir(repo).name == "cc-repo-1"


def test_scope_dir_sanitises_session_name(repo: Path) -> None:
    scope = paths.scope_dir(repo, session="../evil name")
    assert scope.parent == paths.worktree_dir(repo) / "sessions"
    assert scope.name == "---evil-name"


def test_skill_paths_point_into_the_skill() -> None:
    assert (paths.skill_dir() / "scripts" / "context_vigil" / "paths.py").exists()
    assert paths.launcher_path() == paths.skill_dir() / "scripts" / "context-vigil"


def test_launcher_runs_help(run_cli) -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "context-vigil" in result.stdout


def test_launcher_hook_always_exits_zero(run_cli) -> None:
    result = run_cli("hook", "no-such-hook", stdin="not json")
    assert result.returncode == 0


def test_launcher_hook_swallows_broken_interpreter(run_cli) -> None:
    result = run_cli("hook", "nudge", stdin="{}",
                     env={"CONTEXT_VIGIL_PYTHON": "/nonexistent/python"})
    assert result.returncode == 0
    assert result.stdout == ""


def test_worktree_slug_distinguishes_lookalike_paths() -> None:
    slugs = [paths.worktree_slug(Path(p)) for p in ("/r/foo-bar", "/r/foo/bar", "/r/foo.bar")]
    assert len(set(slugs)) == 3
    assert slugs == [paths.worktree_slug(Path(p))
                     for p in ("/r/foo-bar", "/r/foo/bar", "/r/foo.bar")]
    assert all("/" not in s and "." not in s for s in slugs)
