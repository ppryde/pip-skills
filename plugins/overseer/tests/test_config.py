import json
from pathlib import Path
import pytest
from scripts import config


def _init_git(root: Path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def test_central_root_defaults_to_config_dir(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    got = config.central_root(repo)
    assert got == cfgdir / "overseer" / "myrepo"


def test_central_root_honours_config_local(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    (repo / ".overseer").mkdir()
    (repo / ".overseer" / "config.local.json").write_text(
        json.dumps({"central_dir": str(tmp_path / "elsewhere")})
    )
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    assert config.central_root(repo) == tmp_path / "elsewhere"


def test_central_root_env_wins(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    (repo / ".overseer").mkdir()
    (repo / ".overseer" / "config.local.json").write_text(
        json.dumps({"central_dir": str(tmp_path / "elsewhere")})
    )
    monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "envwins"))
    assert config.central_root(repo) == tmp_path / "envwins"


def test_backup_dir_default(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    assert config.backup_dir(repo) == repo / ".overseer" / "backups"


def test_backup_dir_resolves_relative_to_passed_root_not_main_repo_root(tmp_path, monkeypatch):
    """Regression: backup_dir must follow the ACTUAL working tree passed in
    (a linked worktree), never `derive_repo_root` (the main repo root) —
    the committed backup must ride whichever branch is being pushed. Uses a
    real linked worktree, not a bare simulation, to also prove
    `derive_repo_root(worktree) != worktree` here (i.e. the worktree really
    is a distinct root from main, so this exercises the actual divergence
    the bug hinged on)."""
    import subprocess
    main_repo = tmp_path / "main"; main_repo.mkdir(); _init_git(main_repo)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=main_repo, check=True)
    (main_repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main_repo, check=True)

    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feature", str(worktree)],
        cwd=main_repo, check=True,
    )

    from scripts.store import derive_repo_root
    assert derive_repo_root(worktree) == main_repo.resolve()

    assert config.backup_dir(worktree) == worktree / ".overseer" / "backups"
    # relative custom pref (config.json lives at the shared MAIN root, same
    # as `central_root`/`repo_config_dir` — only `backup_dir`'s RESOLUTION
    # target changes) still resolves the relative path against the
    # worktree, not main
    (main_repo / ".overseer").mkdir(parents=True, exist_ok=True)
    (main_repo / ".overseer" / "config.json").write_text(
        json.dumps({"backup_dir": "custom/backups"})
    )
    assert config.backup_dir(worktree) == worktree / "custom" / "backups"
