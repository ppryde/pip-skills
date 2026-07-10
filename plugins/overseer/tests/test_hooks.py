import json
import os
import shutil
import subprocess
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
STOP = PLUGIN_ROOT / "hooks" / "stop.sh"
SESSION_START = PLUGIN_ROOT / "hooks" / "session-start.sh"
# Resolved once, up front: a test that clobbers $PATH (to simulate a missing
# `tmux`) would otherwise also make the `bash` interpreter itself unresolvable
# via list-form subprocess.run (which looks up the program name in env["PATH"]),
# failing before the script even starts. Invoke via the absolute path instead.
BASH = shutil.which("bash") or "/bin/bash"


def _run(script, payload, env, cwd):
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _base_env(extra):
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    env.update(extra)
    return env


def _promote_and_arm(repo):
    from scripts.cli import main
    main(["--root", str(repo), "init"])
    from scripts import orchestrator as orch
    orch.promote(repo)
    orch.request_clear(repo, "HANDOFF FROM HOOK TEST")
    return orch


class TestStopHook:
    def test_hooks_json_registers_both(self):
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert "Stop" in data["hooks"]
        assert "SessionStart" in data["hooks"]
        ss = data["hooks"]["SessionStart"][0]
        assert "startup" in ss["matcher"] and "clear" in ss["matcher"]

    def test_manual_mode_exits_0_and_keeps_flag(self, tmp_path):
        orch = _promote_and_arm(tmp_path)
        env = _base_env({"OVERSEER_CLEAR_DELAY": "0"})
        env.pop("TMUX", None)
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert orch.clear_flag(tmp_path).exists()  # not consumed in manual mode

    def test_auto_mode_sends_keys_and_exits_0(self, tmp_path):
        orch = _promote_and_arm(tmp_path)
        # fake tmux on PATH records its argv to a marker file
        bindir = tmp_path / "bin"
        bindir.mkdir()
        marker = tmp_path / "tmux-called"
        fake = bindir / "tmux"
        fake.write_text('#!/usr/bin/env bash\necho "$@" >> "%s"\n' % marker)
        fake.chmod(0o755)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "OVERSEER_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert not orch.clear_flag(tmp_path).exists()  # consumed
        deadline = time.time() + 3
        while time.time() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.exists()
        assert "/clear" in marker.read_text()

    def test_induced_failure_still_exits_0(self, tmp_path):
        _promote_and_arm(tmp_path)
        # TMUX set but tmux binary absent from PATH, bad pane target, junk stdin
        env = _base_env({
            "PATH": str(tmp_path / "no-such-bin"),
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%does-not-exist",
            "OVERSEER_CLEAR_DELAY": "0",
        })
        result = subprocess.run(
            [BASH, str(STOP)], input="not json at all",
            env=env, cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestSessionStartHook:
    def test_injects_handoff_json(self, tmp_path):
        orch = _promote_and_arm(tmp_path)
        orch.consume_clear_flag(tmp_path)
        env = _base_env({})
        result = _run(SESSION_START, {"cwd": str(tmp_path), "source": "clear"},
                      env, tmp_path)
        assert result.returncode == 0
        assert "HANDOFF FROM HOOK TEST" in result.stdout
        assert "additionalContext" in result.stdout

    def test_silent_and_exit_0_when_inactive(self, tmp_path):
        from scripts.cli import main
        main(["--root", str(tmp_path), "init"])
        env = _base_env({})
        result = _run(SESSION_START, {"cwd": str(tmp_path), "source": "startup"},
                      env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestManifest:
    def test_plugin_version_bumped(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert data["version"] == "0.5.0"

    def test_hooks_file_present_and_valid(self):
        # The shipped hooks file must exist and parse (Claude Code auto-discovers it).
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert set(data["hooks"]) == {"SessionStart", "Stop"}

    def test_marketplace_version_bumped(self):
        mkt = PLUGIN_ROOT.parent.parent / ".claude-plugin" / "marketplace.json"
        data = json.loads(mkt.read_text())
        assert data["version"] == "1.8.0"
