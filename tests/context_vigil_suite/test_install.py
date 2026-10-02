from __future__ import annotations

import json
from pathlib import Path

import pytest
from context_vigil import config, install, paths

FOREIGN_HOOK = {"hooks": [{"type": "command", "command": "echo mine"}]}


def _settings(cfg: Path) -> dict:
    return json.loads((cfg / "settings.json").read_text())


def _write(cfg: Path, data: dict) -> None:
    (cfg / "settings.json").write_text(json.dumps(data, indent=2) + "\n")


def _ours(entries: list) -> list:
    return [e for e in entries if any(str(paths.launcher_path()) in h["command"]
                                      for h in e["hooks"])]


def test_fresh_install_adds_hooks_and_capture_statusline(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    s = _settings(cfg)
    for event, matcher, name in install.HOOKS:
        mine = [e for e in _ours(s["hooks"][event]) if install.hook_command(name)
                in e["hooks"][0]["command"]]
        assert len(mine) == 1
        assert mine[0].get("matcher") == matcher
    assert "capture.sh" in s["statusLine"]["command"]
    assert s["statusLine"]["refreshInterval"] == 60
    assert paths.install_record_path().exists()


def test_install_preserves_foreign_hooks_and_settings(cfg: Path) -> None:
    _write(cfg, {"model": "opus", "hooks": {e: [FOREIGN_HOOK] for e, _, _ in install.HOOKS}})
    install.apply(install.plan_install(threshold=None))
    s = _settings(cfg)
    assert s["model"] == "opus"
    for event, _, _ in install.HOOKS:
        assert s["hooks"][event][0] == FOREIGN_HOOK


def test_install_is_idempotent(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    first = (cfg / "settings.json").read_text()
    plan = install.plan_install(threshold=None)
    assert all(c.before == c.after for c in plan.changes)
    install.apply(plan)
    assert (cfg / "settings.json").read_text() == first


def test_reinstall_from_moved_skill_replaces_old_entries(cfg: Path) -> None:
    stale = {"hooks": [{"type": "command",
                        "command": '"/old/skill/scripts/context-vigil" hook stop'}]}
    _write(cfg, {"hooks": {"Stop": [stale]}})
    install.apply(install.plan_install(threshold=None))
    commands = [h["command"] for e in _settings(cfg)["hooks"]["Stop"] for h in e["hooks"]]
    assert commands == [install.hook_command("stop")]


def test_uninstall_round_trip_is_byte_identical(cfg: Path) -> None:
    _write(cfg, {"model": "opus", "hooks": {"Stop": [FOREIGN_HOOK]}})
    before = (cfg / "settings.json").read_text()
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_uninstall())
    assert (cfg / "settings.json").read_text() == before
    assert not paths.install_record_path().exists()


def test_existing_script_statusline_is_spliced(cfg: Path) -> None:
    script = cfg / "statusline-command.sh"
    script.write_text('#!/usr/bin/env bash\ninput=$(cat)\necho "hi"\n')
    _write(cfg, {"statusLine": {"type": "command", "command": f"bash {script}"}})
    install.apply(install.plan_install(threshold=None))
    text = script.read_text()
    assert install.SL_START in text and 'printf \'%s\' "$input" |' in text
    assert text.index("input=$(cat)") < text.index(install.SL_START)
    assert _settings(cfg)["statusLine"]["command"] == f"bash {script}"
    install.apply(install.plan_uninstall())
    assert script.read_text() == '#!/usr/bin/env bash\ninput=$(cat)\necho "hi"\n'


def test_statusline_with_other_variable_name(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("payload=$(cat)\n")
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    install.apply(install.plan_install(threshold=None))
    assert '"$payload"' in script.read_text()


def test_statusline_without_slurp_is_manual(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("jq -r .model.display_name\n")
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    plan = install.plan_install(threshold=None)
    assert script not in [c.path for c in plan.changes]
    assert any("ingest" in line for line in plan.manual)


def test_inline_statusline_command_is_manual(cfg: Path) -> None:
    _write(cfg, {"statusLine": {"type": "command", "command": "echo hi"}})
    plan = install.plan_install(threshold=None)
    assert any("ingest" in line for line in plan.manual)
    install.apply(plan)
    assert _settings(cfg)["statusLine"]["command"] == "echo hi"


def test_malformed_settings_refuses(cfg: Path) -> None:
    (cfg / "settings.json").write_text("{nope")
    with pytest.raises(install.InstallError, match="settings.json"):
        install.plan_install(threshold=None)


def test_threshold_written_and_kept(cfg: Path, repo: Path) -> None:
    install.apply(install.plan_install(threshold=60))
    assert config.resolve(repo)["context.threshold"] == (60, "global")
    install.apply(install.plan_install(threshold=None))
    assert config.threshold(repo) == 60


def test_cli_dry_run_changes_nothing(run_cli, cfg: Path) -> None:
    result = run_cli("install")
    assert result.returncode == 0
    assert "--yes" in result.stdout and "+++" in result.stdout
    assert not (cfg / "settings.json").exists()


def test_cli_apply(run_cli, cfg: Path) -> None:
    result = run_cli("install", "--yes", "--threshold", "50")
    assert result.returncode == 0, result.stderr
    assert (cfg / "settings.json").exists()
    assert "new sessions" in result.stdout
