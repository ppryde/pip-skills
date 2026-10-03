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


def test_apply_records_before_touching_user_files(cfg: Path, monkeypatch) -> None:
    script = cfg / "sl.sh"
    script.write_text("input=$(cat)\n")
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    plan = install.plan_install(threshold=None)

    real = install.write_atomic

    def boom(path, text):
        if path == paths.install_record_path():
            return real(path, text)
        assert paths.install_record_path().exists()
        raise OSError("disk full")

    monkeypatch.setattr(install, "write_atomic", boom)
    with pytest.raises(OSError):
        install.apply(plan)
    assert json.loads(paths.install_record_path().read_text())["statusline"]["kind"] == "spliced"


def test_failed_write_leaves_no_tmp(cfg: Path, monkeypatch) -> None:
    import os as _os
    plan = install.plan_install(threshold=None)
    monkeypatch.setattr(_os, "replace", lambda *a: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        install.apply(plan)
    assert not list(cfg.glob("*.context-vigil.tmp"))


def test_uninstall_without_record_says_so(cfg: Path) -> None:
    assert any("no install record" in m for m in install.plan_uninstall().manual)


def test_cli_oserror_is_clean_error(run_cli, cfg: Path) -> None:
    (cfg / "settings.json").mkdir(parents=True)
    result = run_cli("install", "--yes")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr and "error:" in result.stderr


def test_script_mode_preserved(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("input=$(cat)\n")
    script.chmod(0o755)
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    (cfg / "settings.json").chmod(0o600)
    install.apply(install.plan_install(threshold=None))
    assert script.stat().st_mode & 0o777 == 0o755
    assert (cfg / "settings.json").stat().st_mode & 0o777 == 0o600
    install.apply(install.plan_uninstall())
    assert script.stat().st_mode & 0o777 == 0o755


def test_symlinked_settings_survives(cfg: Path, iso: Path) -> None:
    real = iso / "dotfiles-settings.json"
    real.write_text("{}\n")
    (cfg / "settings.json").symlink_to(real)
    install.apply(install.plan_install(threshold=None))
    assert (cfg / "settings.json").is_symlink()
    assert "hooks" in json.loads(real.read_text())


def test_unsplice_without_end_marker_is_untouched(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("input=$(cat)\n")
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    install.apply(install.plan_install(threshold=None))
    broken = script.read_text().replace(install.SL_END, "") + "echo user-after\n"
    script.write_text(broken)
    plan = install.plan_uninstall()
    assert script not in [c.path for c in plan.changes]
    assert any("look damaged" in m for m in plan.manual)
    install.apply(plan)
    assert script.read_text() == broken


def test_uninstall_keeps_preexisting_empty_settings(cfg: Path) -> None:
    _write(cfg, {"hooks": {}})
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_uninstall())
    assert (cfg / "settings.json").read_text() == "{}\n"
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_uninstall())
    assert (cfg / "settings.json").exists()


def test_uninstall_removes_settings_it_created(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_uninstall())
    assert not (cfg / "settings.json").exists()


def test_dry_run_announces_threshold_write(run_cli, cfg: Path) -> None:
    result = run_cli("install", "--threshold", "50")
    assert "will set context.threshold = 50" in result.stdout
    assert not (cfg / "settings.json").exists()
    applied = run_cli("install", "--yes", "--threshold", "50")
    assert "will set context.threshold = 50" in applied.stdout


@pytest.mark.parametrize("hooks", ["oops", {"Stop": "oops"}])
def test_malformed_hooks_shape_refuses(cfg: Path, hooks) -> None:
    _write(cfg, {"hooks": hooks})
    before = (cfg / "settings.json").read_text()
    with pytest.raises(install.InstallError, match="hooks"):
        install.plan_install(threshold=None)
    with pytest.raises(install.InstallError, match="hooks"):
        install.plan_uninstall()
    assert (cfg / "settings.json").read_text() == before


def _record_skill_dir(old: str) -> None:
    record = json.loads(paths.install_record_path().read_text())
    record["skill_dir"] = old
    paths.install_record_path().write_text(json.dumps(record))


def test_reinstall_repoints_capture_statusline_from_old_skill_dir(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    _record_skill_dir("/old/skill")
    s = _settings(cfg)
    s["statusLine"]["command"] = 'bash "/old/skill/scripts/capture.sh"'
    _write(cfg, s)
    plan = install.plan_install(threshold=None)
    assert plan.record["statusline"] == {"kind": "capture"}
    assert not plan.manual
    install.apply(plan)
    assert _settings(cfg)["statusLine"]["command"] == install.capture_command()


def test_uninstall_removes_capture_statusline_from_recorded_old_skill_dir(
        cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    _record_skill_dir("/old/skill")
    s = _settings(cfg)
    s["statusLine"]["command"] = 'bash "/old/skill/scripts/capture.sh"'
    _write(cfg, s)
    install.apply(install.plan_uninstall())
    assert not (cfg / "settings.json").exists()


def test_reinstall_rewrites_stale_spliced_block(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("#!/bin/bash\ninput=$(cat)\necho hi\n")
    script.chmod(0o755)
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    install.apply(install.plan_install(threshold=None))
    old = '"/old/skill/scripts/context-vigil"'
    stale = script.read_text().replace(f'"{paths.launcher_path()}"', old)
    assert old in stale
    script.write_text(stale)
    _record_skill_dir("/old/skill")
    install.apply(install.plan_install(threshold=None))
    text = script.read_text()
    assert "/old/skill" not in text
    assert text.count(install.SL_START) == 1
    assert install.ingest_command("input") in text
    install.apply(install.plan_uninstall())
    assert script.read_text() == "#!/bin/bash\ninput=$(cat)\necho hi\n"


def test_non_ascii_settings_round_trip(cfg: Path) -> None:
    (cfg / "settings.json").write_text(
        json.dumps({"note": "café — 日本"}, ensure_ascii=False) + "\n", encoding="utf-8")
    install.apply(install.plan_install(threshold=None))
    text = (cfg / "settings.json").read_text(encoding="utf-8")
    assert "café — 日本" in text and "\\u" not in text
