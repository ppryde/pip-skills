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


@pytest.mark.parametrize(
    "key, getter, default, good_raw, good_value, bad_raws, env_name, env_raw, env_value,"
    " fallback_env",
    [
        pytest.param(
            "nudge.repeat_step", "repeat_step", 5, "10", 10, ("0", "51", "x"),
            "CONTEXT_VIGIL_REPEAT_STEP", "7", 7,
            # an invalid env value falls through to the stored (global) one
            ("99", (10, "global")), id="repeat_step"),
        pytest.param(
            "handover.max_tokens", "handover_max_tokens", 8000, "12000", 12000,
            ("0", "-5", "abc"), "CONTEXT_VIGIL_HANDOVER_MAX_TOKENS", "9000", 9000,
            None, id="handover_max_tokens"),
        pytest.param(
            "handover.cooldown_seconds", "cooldown_seconds", 60, "0", 0, ("-1", "3601", "x"),
            "CONTEXT_VIGIL_COOLDOWN_SECONDS", "120", 120,
            None, id="handover_cooldown_seconds"),
    ])
def test_numeric_setting_validated_and_env(
        repo: Path, monkeypatch: pytest.MonkeyPatch, key, getter, default, good_raw,
        good_value, bad_raws, env_name, env_raw, env_value, fallback_env) -> None:
    read = getattr(config, getter)
    assert read(repo) == default
    config.set_value(repo, key, good_raw)
    assert read(repo) == good_value
    for bad in bad_raws:
        with pytest.raises(config.ConfigError):
            config.set_value(repo, key, bad)
    monkeypatch.setenv(env_name, env_raw)
    assert config.resolve(repo)[key] == (env_value, "env")
    if fallback_env is not None:
        monkeypatch.setenv(env_name, fallback_env[0])
        assert config.resolve(repo)[key] == fallback_env[1]
