import json
import os
import shutil
import subprocess
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
STOP = PLUGIN_ROOT / "hooks" / "stop.sh"
SESSION_START = PLUGIN_ROOT / "hooks" / "session-start.sh"
NUDGE = PLUGIN_ROOT / "hooks" / "nudge-hook.sh"
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
    from scripts import state as st
    st.begin(repo)
    st.request_clear(repo, "HANDOFF FROM HOOK TEST")
    return st


class TestStopHook:
    def test_hooks_json_registers_all_three(self):
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert "Stop" in data["hooks"]
        assert "SessionStart" in data["hooks"]
        assert "UserPromptSubmit" in data["hooks"]
        ss = data["hooks"]["SessionStart"][0]
        assert "startup" in ss["matcher"] and "clear" in ss["matcher"]
        ups = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        assert ups["command"].endswith("nudge-hook.sh")

    def test_hooks_json_registers_nudge_hook_on_task_boundaries(self):
        # Unattended (auto-handover) runs receive no UserPromptSubmit — the
        # nudge must also fire headless. Rather than prodding on EVERY tool
        # call, it fires at work boundaries: the task-list transitions
        # (TaskCreate/TaskUpdate) that orchestrated runs mark between tasks.
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert "PostToolUse" in data["hooks"]
        ptu = data["hooks"]["PostToolUse"][0]
        assert ptu["matcher"] == "TaskCreate|TaskUpdate"
        assert ptu["hooks"][0]["command"].endswith("nudge-hook.sh")

    def test_manual_mode_exits_0_and_keeps_flag(self, tmp_path):
        st = _promote_and_arm(tmp_path)
        env = _base_env({"VIGIL_CLEAR_DELAY": "0"})
        env.pop("TMUX", None)
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert st.clear_flag(tmp_path).exists()  # not consumed in manual mode

    def test_manual_mode_armed_emits_loud_line(self, tmp_path):
        st = _promote_and_arm(tmp_path)
        env = _base_env({"VIGIL_CLEAR_DELAY": "0"})
        env.pop("TMUX", None)
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        # Plain Stop stdout is swallowed to the debug log — the loud line MUST go
        # out on the user-visible systemMessage channel as valid JSON.
        payload = json.loads(result.stdout.strip())
        assert "tmux is unavailable" in payload["systemMessage"]
        assert "type /clear" in payload["systemMessage"]
        assert "additionalContext" not in result.stdout  # never forces continuation
        assert st.clear_flag(tmp_path).exists()  # loud message never consumes the flag

    def test_dead_tmux_server_falls_through_to_loud_manual(self, tmp_path):
        # $TMUX is set but the server is dead: `tmux has-session` fails. The probe
        # must catch this BEFORE the consuming stop-hook runs, so the flag is
        # preserved and the user gets the same loud systemMessage as no-tmux.
        st = _promote_and_arm(tmp_path)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "tmux"
        fake.write_text(
            '#!/usr/bin/env bash\n'
            'if [ "$1" = "has-session" ]; then exit 1; fi\n'
            'exit 0\n'
        )
        fake.chmod(0o755)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "VIGIL_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        payload = json.loads(result.stdout.strip())
        assert "tmux is unavailable" in payload["systemMessage"]
        assert st.clear_flag(tmp_path).exists()  # NOT consumed — dispatch impossible

    def test_manual_mode_unarmed_is_silent(self, tmp_path):
        from scripts import state as st
        st.begin(tmp_path)  # active, but no handover armed
        env = _base_env({"VIGIL_CLEAR_DELAY": "0"})
        env.pop("TMUX", None)
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_manual_mode_silent_when_inactive(self, tmp_path):
        env = _base_env({"VIGIL_CLEAR_DELAY": "0"})
        env.pop("TMUX", None)
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_auto_mode_sends_keys_and_exits_0(self, tmp_path):
        st = _promote_and_arm(tmp_path)
        # fake tmux on PATH: the has-session liveness probe succeeds silently;
        # only send-keys records its argv to the marker (so the wait loop below
        # cannot race on the probe having merely created the file).
        bindir = tmp_path / "bin"
        bindir.mkdir()
        marker = tmp_path / "tmux-called"
        fake = bindir / "tmux"
        fake.write_text(
            '#!/usr/bin/env bash\n'
            'if [ "$1" = "has-session" ]; then exit 0; fi\n'
            'echo "$@" >> "%s"\n' % marker
        )
        fake.chmod(0o755)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "VIGIL_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert not st.clear_flag(tmp_path).exists()  # consumed
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
            "VIGIL_CLEAR_DELAY": "0",
        })
        result = subprocess.run(
            [BASH, str(STOP)], input="not json at all",
            env=env, cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestSessionStartHook:
    def test_injects_handoff_json(self, tmp_path):
        st = _promote_and_arm(tmp_path)
        st.consume_clear_flag(tmp_path)
        env = _base_env({})
        result = _run(SESSION_START, {"cwd": str(tmp_path), "source": "clear"},
                      env, tmp_path)
        assert result.returncode == 0
        assert "HANDOFF FROM HOOK TEST" in result.stdout
        assert "additionalContext" in result.stdout

    def test_silent_and_exit_0_when_inactive(self, tmp_path):
        # no `begin` — vigil is not watching this repo, so the hook must be inert
        env = _base_env({})
        result = _run(SESSION_START, {"cwd": str(tmp_path), "source": "startup"},
                      env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestNudgeHookScript:
    def _census(self, tmp_path, pct):
        import os
        import time
        store = tmp_path / "census" / "status.json"
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({
            "sessions": {"s1": {
                "worktree_cwd": os.path.realpath(str(tmp_path)),
                "updated_at": time.time(),
                "payload": {"context_window": {"used_percentage": pct}},
            }}
        }))
        return store

    def test_nudges_over_threshold(self, tmp_path):
        from scripts import state as st
        st.begin(tmp_path)
        store = self._census(tmp_path, 40)
        env = _base_env({"CENSUS_STORE": str(store)})
        result = _run(NUDGE, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert "additionalContext" in result.stdout
        assert "40%" in result.stdout
        assert st.gate_active(tmp_path)

    def test_silent_under_threshold(self, tmp_path):
        from scripts import state as st
        st.begin(tmp_path)
        store = self._census(tmp_path, 10)
        env = _base_env({"CENSUS_STORE": str(store)})
        result = _run(NUDGE, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_silent_when_inactive(self, tmp_path):
        store = self._census(tmp_path, 90)
        env = _base_env({"CENSUS_STORE": str(store)})
        result = _run(NUDGE, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestPackaging:
    def test_plugin_manifest_valid(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert data["name"] == "vigil"
        assert data["version"] == "0.1.0"

    def test_marketplace_lists_vigil(self):
        mkt = PLUGIN_ROOT.parent.parent / ".claude-plugin" / "marketplace.json"
        data = json.loads(mkt.read_text())
        names = [p["name"] for p in data["plugins"]]
        assert "vigil" in names

    def test_skill_and_command_present(self):
        assert (PLUGIN_ROOT / "skills" / "vigil" / "SKILL.md").exists()
        assert (PLUGIN_ROOT / "commands" / "handover.md").exists()
