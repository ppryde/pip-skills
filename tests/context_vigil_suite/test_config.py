from __future__ import annotations

import json
from pathlib import Path

import pytest
from context_vigil import config, paths


def test_defaults(repo: Path) -> None:
    assert config.load(repo) == {
        "context.threshold": 35, "context.window": 200000, "context.mode": "local",
        "nudge.repeat_step": 5, "handover.max_tokens": 8000,
        "handover.cooldown_seconds": 60, "handover.archive_keep": 20,
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


def test_repeat_step_validated_and_env(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.repeat_step(repo) == 5
    config.set_value(repo, "nudge.repeat_step", "10")
    assert config.repeat_step(repo) == 10
    for bad in ("0", "51", "x"):
        with pytest.raises(config.ConfigError):
            config.set_value(repo, "nudge.repeat_step", bad)
    monkeypatch.setenv("CONTEXT_VIGIL_REPEAT_STEP", "7")
    assert config.resolve(repo)["nudge.repeat_step"] == (7, "env")
    monkeypatch.setenv("CONTEXT_VIGIL_REPEAT_STEP", "99")
    assert config.resolve(repo)["nudge.repeat_step"] == (10, "global")


def test_handover_max_tokens_validated_and_env(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.handover_max_tokens(repo) == 8000
    config.set_value(repo, "handover.max_tokens", "12000")
    assert config.handover_max_tokens(repo) == 12000
    for bad in ("0", "-5", "abc"):
        with pytest.raises(config.ConfigError):
            config.set_value(repo, "handover.max_tokens", bad)
    monkeypatch.setenv("CONTEXT_VIGIL_HANDOVER_MAX_TOKENS", "9000")
    assert config.resolve(repo)["handover.max_tokens"] == (9000, "env")


def test_handover_cooldown_seconds_validated_and_env(repo: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.cooldown_seconds(repo) == 60
    config.set_value(repo, "handover.cooldown_seconds", "0")
    assert config.cooldown_seconds(repo) == 0
    for bad in ("-1", "3601", "x"):
        with pytest.raises(config.ConfigError):
            config.set_value(repo, "handover.cooldown_seconds", bad)
    monkeypatch.setenv("CONTEXT_VIGIL_COOLDOWN_SECONDS", "120")
    assert config.resolve(repo)["handover.cooldown_seconds"] == (120, "env")
