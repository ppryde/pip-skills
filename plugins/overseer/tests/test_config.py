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
