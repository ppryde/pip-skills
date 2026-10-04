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
    run(tmp_path, "install")
    run(tmp_path, "install")
    assert settings(tmp_path)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == PLUGIN


def test_uninstall_removes_only_ours(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": f"/a:{PLUGIN}:/b"}}))
    assert run(tmp_path, "uninstall").returncode == 0
    assert settings(tmp_path)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "/a:/b"


# Same fixture string as CLASSIC_CMD in plugins/context-vigil-mod/tests/interlock.test.ts (Task 10).
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
