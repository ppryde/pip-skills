"""install.sh edits only env.CLAUDE_CODE_PLUGIN_DIRS in the account's own settings.json.

Isolation: every run pins CLAUDE_CONFIG_DIR and HOME into tmp_path (repo CLAUDE.md).
"""
import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "plugins" / "context-vigil-mod" / "scripts" / "install.sh"
PLUGIN = str(SCRIPT.parent.parent)


def run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "HOME": str(tmp_path / "home")}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def settings(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "cfg" / "settings.json").read_text())


def test_install_creates_and_appends(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/other"}, "model": "opus"}))
    r = run(tmp_path, "install")
    assert r.returncode == 0, r.stderr
    s = settings(tmp_path)
    assert s["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == f"/other:{PLUGIN}"
    assert s["model"] == "opus"


def test_install_is_idempotent(tmp_path):
    assert run(tmp_path, "install").returncode == 0
    second = run(tmp_path, "install")
    assert second.returncode == 0, second.stderr
    assert "already installed" in second.stdout
    assert settings(tmp_path)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == PLUGIN


def test_uninstall_removes_only_ours(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": f"/a:{PLUGIN}:/b"}}))
    assert run(tmp_path, "uninstall").returncode == 0
    assert settings(tmp_path)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "/a:/b"


# Same fixture string as CLASSIC_CMD in interlock.test.ts beside this file (Task 10).
CLASSIC_CMD = '"/s/context-vigil/scripts/context-vigil" hook stop'


def test_refuses_while_classic_hooks_are_installed(tmp_path):
    (tmp_path / "cfg").mkdir()
    classic = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": CLASSIC_CMD}]}]}}
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps(classic))
    r = run(tmp_path, "install")
    assert r.returncode == 3
    assert "uninstall classic" in r.stderr
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in (tmp_path / "cfg" / "settings.json").read_text()


def test_status(tmp_path):
    assert "not installed" in run(tmp_path, "status").stdout
    run(tmp_path, "install")
    out = run(tmp_path, "status").stdout
    assert "context-vigil-mod: installed" in out
    assert "not installed" not in out


def test_other_hooks_do_not_block_install(tmp_path):
    (tmp_path / "cfg").mkdir()
    other = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude-personal/census/five-hour-guard.py"}]}]}}
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps(other))
    assert run(tmp_path, "install").returncode == 0
    s = settings(tmp_path)
    assert s["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == PLUGIN
    assert s["hooks"] == other["hooks"]


def test_install_keeps_a_symlinked_settings_file_and_its_mode(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    real = tmp_path / "dotfiles-settings.json"
    real.write_text("{}")
    real.chmod(0o644)
    (cfg / "settings.json").symlink_to(real)
    assert run(tmp_path, "install").returncode == 0
    assert (cfg / "settings.json").is_symlink()
    assert PLUGIN in real.read_text()
    assert (real.stat().st_mode & 0o777) == 0o644
    assert not list(cfg.glob(".settings.*"))


def test_status_creates_nothing(tmp_path):
    assert run(tmp_path, "status").returncode == 0
    assert not (tmp_path / "cfg").exists()


def test_invalid_json_leaves_original_and_no_temp_file(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text("{ not json")
    r = run(tmp_path, "install")
    assert r.returncode != 0
    assert (cfg / "settings.json").read_text() == "{ not json"
    assert not list(cfg.glob(".settings.*"))


def test_uninstall_with_nothing_to_remove_is_a_no_op(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text('{"model":"opus"}')
    assert run(tmp_path, "uninstall").returncode == 0
    assert (cfg / "settings.json").read_text() == '{"model":"opus"}'
