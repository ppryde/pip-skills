from __future__ import annotations

import json
from pathlib import Path

import pytest
from context_vigil import config, paths


def test_defaults(repo: Path) -> None:
    assert config.load(repo) == {
        "context.threshold": 35, "context.window": 200000, "context.mode": "local",
    }
    assert config.resolve(repo)["context.threshold"] == (35, "default")


def test_global_beats_default(repo: Path) -> None:
    config.set_value(repo, "context.threshold", "60")
    assert config.resolve(repo)["context.threshold"] == (60, "global")


def test_worktree_beats_global(repo: Path, iso: Path) -> None:
    other = iso / "other"
    other.mkdir()
    config.set_value(repo, "context.threshold", "60")
    config.set_value(repo, "context.threshold", "40", worktree=True)
    assert config.resolve(repo)["context.threshold"] == (40, "worktree")
    assert config.resolve(other)["context.threshold"] == (60, "global")


def test_env_beats_everything(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config.set_value(repo, "context.threshold", "40", worktree=True)
    monkeypatch.setenv("CONTEXT_VIGIL_THRESHOLD", "70")
    assert config.resolve(repo)["context.threshold"] == (70, "env")


def test_invalid_env_falls_through(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_THRESHOLD", "lots")
    assert config.resolve(repo)["context.threshold"] == (35, "default")


def test_corrupt_file_falls_through(repo: Path) -> None:
    path = paths.global_config_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert config.threshold(repo) == 35


def test_invalid_stored_value_falls_through(repo: Path) -> None:
    path = paths.global_config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"context.threshold": 500}))
    assert config.threshold(repo) == 35


@pytest.mark.parametrize("key,raw", [
    ("context.threshold", "0"), ("context.threshold", "96"), ("context.threshold", "x"),
    ("context.window", "0"), ("context.mode", "cloud"), ("nope", "1"),
])
def test_set_rejects(repo: Path, key: str, raw: str) -> None:
    with pytest.raises(config.ConfigError):
        config.set_value(repo, key, raw)


def test_cli_set_and_get(run_cli, repo: Path) -> None:  # type: ignore[no-untyped-def]
    assert run_cli("config", "set", "context.threshold", "55", cwd=repo).returncode == 0
    out = run_cli("config", "get", "context.threshold", cwd=repo)
    assert out.stdout.strip() == "context.threshold = 55 (global)"


def test_cli_set_rejects_with_range(run_cli, repo: Path) -> None:  # type: ignore[no-untyped-def]
    out = run_cli("config", "set", "context.threshold", "99", cwd=repo)
    assert out.returncode == 1
    assert "1–95" in out.stderr
