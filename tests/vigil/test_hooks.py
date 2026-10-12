import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "vigil"
STOP = PLUGIN_ROOT / "hooks" / "stop.sh"
SESSION_START = PLUGIN_ROOT / "hooks" / "session-start.sh"
NUDGE = PLUGIN_ROOT / "hooks" / "nudge-hook.sh"
# Resolved once, up front: a test that clobbers $PATH (to simulate a missing
# `tmux`) would otherwise also make the `bash` interpreter itself unresolvable
# via list-form subprocess.run (which looks up the program name in env["PATH"]),
# failing before the script even starts. Invoke via the absolute path instead.
BASH = shutil.which("bash") or "/bin/bash"


RULE = "─" * 40
# A idle Claude Code prompt: the placeholder is drawn dim (SGR 2) so it is not "typed".
SAFE_SCREEN = f"output\n{RULE}\n❯ \x1b[2mTry something\x1b[0m\n{RULE}\n"
TYPED_SCREEN = f"output\n{RULE}\n❯ half a sentence\n{RULE}\n"
# Live captures, Claude Code 2.1.296, session named "Great Refactoring probe": the
# name sits in the upper rule; a running turn shows "esc to interrupt" in the footer
# under the box, and it is STILL there while the Stop hook runs.
NAMED_RULE = "\x1b[38;5;244m" + "─" * 94 + " Great Refactoring probe ─"
LOWER_RULE = "\x1b[38;5;244m" + "─" * 120
FOOTER = "\x1b[39m  \x1b[38;5;220m⏵⏵ auto mode on\x1b[38;5;246m (shift+tab to cycle){} · ← 1 agent\x1b[39m"
NAMED_SCREEN = (
    f"✽ Cerebrating… (1s · thinking)\n{NAMED_RULE}\n\x1b[39m❯\xa0\n{LOWER_RULE}\n"
    + FOOTER.format("") + "\n"
)
BUSY_SCREEN = (
    f"✽ Cerebrating… (1s · thinking)\n{NAMED_RULE}\n\x1b[38;5;246m❯\xa0\x1b[39m\n{LOWER_RULE}\n"
    + FOOTER.format(" · esc to interrupt") + "\n"
)
# The phrase in transcript text above an idle box is not a running turn.
TRANSCRIPT_MENTIONS_BUSY = f"BUSY_PATTERN matches esc to interrupt in the footer\n{SAFE_SCREEN}"
DIALOG_SCREEN = (
    f"Allow this tool?\n❯ 1. Yes\n  2. No\nEnter to select · Esc to cancel\n"
)


def _fake_tmux(tmp_path, screen, capture_fails=False, in_mode="0", later_screen=None, name="tmux",
               sequence=None):
    """A fake tmux on a private bin dir: has-session ok, capture-pane prints `screen`
    (or fails; from the 2nd capture on, `later_screen` when given; with `sequence`,
    capture n prints sequence[n], the last one repeating), display-message prints
    `in_mode`; every other call (rename-window, send-keys) appends its argv to
    `marker`. Every call is logged to `all-calls`. Never a real tmux server."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    screens = sequence or [screen, screen if later_screen is None else later_screen]
    for i, text in enumerate(screens):
        (tmp_path / f"screen-{i}.txt").write_text(text)
    last = len(screens) - 1
    counter = tmp_path / "captures"
    marker = tmp_path / "tmux-called"
    capture = "exit 1" if capture_fails else (
        f'n=$(cat "{counter}" 2>/dev/null || echo 0); echo $((n+1)) > "{counter}"; '
        f'[ "$n" -gt {last} ] && n={last}; cat "{tmp_path}/screen-$n.txt"; exit 0'
    )
    fake = bindir / name
    fake.write_text(
        '#!/usr/bin/env bash\n'
        f'echo "$@" >> "{tmp_path / "all-calls"}"\n'
        'if [ "$1" = "has-session" ]; then exit 0; fi\n'
        f'if [ "$1" = "display-message" ]; then echo {in_mode}; exit 0; fi\n'
        f'if [ "$1" = "capture-pane" ]; then {capture}; fi\n'
        f'echo "$@" >> "{marker}"\n'
    )
    fake.chmod(0o755)
    return bindir, marker


def _auto_env(bindir):
    return _base_env({
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "TMUX": "/tmp/fake,1,0",
        "TMUX_PANE": "%9",
        "VIGIL_CLEAR_DELAY": "0",
    })


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


def _promote_and_arm(repo, pane=None):
    """Arm from the tmux pane lineage the hook will run in (None = outside tmux)."""
    from scripts import state as st
    saved = os.environ.get("TMUX_PANE")
    if pane is None:
        os.environ.pop("TMUX_PANE", None)
    else:
        os.environ["TMUX_PANE"] = pane
    try:
        st.begin(repo)
        st.request_clear(repo, "HANDOFF FROM HOOK TEST")
    finally:
        if saved is None:
            os.environ.pop("TMUX_PANE", None)
        else:
            os.environ["TMUX_PANE"] = saved
    return st


def _wait_calls(marker, count, timeout=5):
    deadline = time.time() + timeout
    calls: list[str] = []
    while time.time() < deadline and len(calls) < count:
        if marker.exists():
            calls = marker.read_text().strip().splitlines()
        time.sleep(0.05)
    return calls


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

    def test_dead_tmux_server_falls_through_to_loud_manual(self, tmp_path, monkeypatch):
        # $TMUX is set but the server is dead: `tmux has-session` fails. The probe
        # must catch this BEFORE the consuming stop-hook runs, so the flag is
        # preserved and the user gets the same loud systemMessage as no-tmux.
        st = _promote_and_arm(tmp_path, "%9")
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
        monkeypatch.setenv("TMUX_PANE", "%9")
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
        st = _promote_and_arm(tmp_path, "%9")
        # fake tmux on PATH: the has-session liveness probe succeeds silently;
        # only send-keys records its argv to the marker (so the wait loop below
        # cannot race on the probe having merely created the file).
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "VIGIL_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        deadline = time.time() + 3
        while time.time() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.exists()
        assert "/clear" in marker.read_text()

    def test_auto_mode_renames_window_before_clear_when_title_armed(self, tmp_path, monkeypatch):
        from scripts import state as st
        monkeypatch.setenv("TMUX_PANE", "%9")  # arm from the pane the hook runs in
        st.begin(tmp_path)
        st.request_clear(tmp_path, "HANDOFF FROM HOOK TEST", title="fix the auth bug")
        # fake tmux on PATH: has-session succeeds silently; rename-window and
        # send-keys both append their argv to the marker, in call order.
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "VIGIL_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        # The clear runs in a detached process: wait for BOTH calls, not just the
        # first line landing, or a loaded machine reads the file between them.
        deadline = time.time() + 5
        calls: list[str] = []
        while time.time() < deadline and len(calls) < 2:
            if marker.exists():
                calls = marker.read_text().strip().splitlines()
            time.sleep(0.05)
        assert marker.exists()
        assert calls[0] == "rename-window -t %9 -- fix the auth bug"
        assert calls[1] == "send-keys -t %9 /clear Enter"

    def test_auto_mode_skips_rename_when_no_title_armed(self, tmp_path):
        st = _promote_and_arm(tmp_path, "%9")  # no title
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "VIGIL_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        deadline = time.time() + 3
        while time.time() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.exists()
        calls = marker.read_text().strip().splitlines()
        assert calls == ["send-keys -t %9 /clear Enter"]  # no rename-window call

    def test_safe_pane_sends_clear(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")  # read the flag from the hook's pane lineage
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]
        assert not st.clear_flag(tmp_path).exists()

    def _assert_held(self, tmp_path, result, marker, st, why):
        assert result.returncode == 0
        message = json.loads(result.stdout.strip())["systemMessage"]
        assert "handover pending" in message and "not sent" in message and why in message
        assert st.clear_flag(tmp_path).exists()  # still armed
        time.sleep(0.3)
        assert not marker.exists()  # no send-keys, no rename-window

    def test_non_empty_prompt_holds(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")  # read the flag from the hook's pane lineage
        bindir, marker = _fake_tmux(tmp_path, TYPED_SCREEN)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        self._assert_held(tmp_path, result, marker, st, "prompt box is not empty")

    def test_open_dialog_holds(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")  # read the flag from the hook's pane lineage
        bindir, marker = _fake_tmux(tmp_path, DIALOG_SCREEN)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        self._assert_held(tmp_path, result, marker, st, "no empty prompt box")

    def test_dialog_footer_under_a_prompt_box_holds(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")  # read the flag from the hook's pane lineage
        screen = SAFE_SCREEN + "Enter to confirm · Esc to cancel\n"
        bindir, marker = _fake_tmux(tmp_path, screen)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        self._assert_held(tmp_path, result, marker, st, "dialog or permission prompt")

    def test_busy_during_the_hook_and_idle_after_the_delay_sends_clear(self, tmp_path, monkeypatch):
        # The in-hook check ignores "esc to interrupt": the footer shows it while
        # the Stop hook itself runs, so honouring it would hold every handover.
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, BUSY_SCREEN, later_screen=NAMED_SCREEN)
        env = _auto_env(bindir)
        env["VIGIL_CLEAR_DELAY"] = "0.3"
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]
        assert not st.clear_flag(tmp_path).exists()

    def _busy_env(self, bindir, wait="3"):
        env = _auto_env(bindir)
        env["VIGIL_CLEAR_DELAY"] = "0"
        env["VIGIL_BUSY_WAIT"] = wait
        return env

    def test_busy_busy_idle_after_the_delay_sends_clear(self, tmp_path, monkeypatch):
        # Another Stop hook is still running: the footer stays busy for two
        # re-checks; the busy-only hold is retried, then /clear goes out.
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, None, sequence=[
            BUSY_SCREEN, BUSY_SCREEN, BUSY_SCREEN, NAMED_SCREEN])
        result = _run(STOP, {"cwd": str(tmp_path)}, self._busy_env(bindir), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]
        assert int((tmp_path / "captures").read_text()) == 4
        assert not st.clear_flag(tmp_path).exists()

    def test_busy_for_the_whole_window_holds_and_stays_armed(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, BUSY_SCREEN)
        # whole seconds against bash's $SECONDS: a 2s wait is 1-2s in practice
        result = _run(STOP, {"cwd": str(tmp_path)}, self._busy_env(bindir, wait="2"), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        time.sleep(3.5)  # past the window plus a poll
        tries = int((tmp_path / "captures").read_text())
        assert tries >= 3  # the in-hook check plus more than one re-check
        time.sleep(0.8)
        assert int((tmp_path / "captures").read_text()) == tries  # it gave up
        assert not marker.exists()
        assert st.clear_flag(tmp_path).exists()

    def test_busy_then_typed_text_drops_at_once(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, None, sequence=[
            BUSY_SCREEN, BUSY_SCREEN, TYPED_SCREEN, NAMED_SCREEN])
        result = _run(STOP, {"cwd": str(tmp_path)}, self._busy_env(bindir), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        time.sleep(2.5)
        assert int((tmp_path / "captures").read_text()) == 3  # no retry after typed text
        assert not marker.exists()
        assert st.clear_flag(tmp_path).exists()

    def test_named_session_sends_clear(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, NAMED_SCREEN)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]
        assert not st.clear_flag(tmp_path).exists()

    def test_transcript_mentioning_esc_to_interrupt_still_sends(self, tmp_path, monkeypatch):
        _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, TRANSCRIPT_MENTIONS_BUSY)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]

    def test_turn_starting_during_the_delay_holds_and_stays_armed(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        # idle at Stop; the person submits a prompt during the delay (box empty again)
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN, later_screen=BUSY_SCREEN)
        env = _auto_env(bindir)
        env["VIGIL_CLEAR_DELAY"] = "0.5"
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        time.sleep(1.5)  # the detached subshell has run its re-check
        assert not marker.exists()  # no rename-window, no send-keys
        assert st.clear_flag(tmp_path).exists()  # never consumed

    def test_unarmed_stop_spawns_no_dispatch(self, tmp_path, monkeypatch):
        from scripts import state as st
        monkeypatch.setenv("TMUX_PANE", "%9")
        st.begin(tmp_path)  # active, nothing armed
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        env = _auto_env(bindir)
        env["VIGIL_CLEAR_DELAY"] = "0.3"
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        # Arm DURING what would have been the delay: a stale subshell would eat it.
        st.request_clear(tmp_path, "ARMED AFTER THE STOP")
        time.sleep(1.2)
        calls = (tmp_path / "all-calls").read_text().splitlines()
        assert calls == ["has-session"]  # no display-message, capture-pane or send-keys
        assert not marker.exists()
        assert st.clear_flag(tmp_path).exists()  # left for the next Stop

    def test_capture_failure_holds_with_system_message(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")  # read the flag from the hook's pane lineage
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN, capture_fails=True)
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        self._assert_held(tmp_path, result, marker, st, "could not be read")

    def test_stop_hook_active_short_circuits(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")  # read the flag from the hook's pane lineage
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        payload = {"cwd": str(tmp_path), "stop_hook_active": True}
        result = _run(STOP, payload, _auto_env(bindir), tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert st.clear_flag(tmp_path).exists()  # not consumed
        time.sleep(0.3)
        assert not marker.exists()

    def test_pane_turning_unsafe_during_the_delay_holds_and_stays_armed(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        # safe at the first check, then the person has typed something by the re-check
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN, later_screen=TYPED_SCREEN)
        env = _auto_env(bindir)
        env["VIGIL_CLEAR_DELAY"] = "0.5"
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert st.clear_flag(tmp_path).exists()  # still armed through the delay
        time.sleep(1.5)  # the detached subshell has run its re-check
        assert not marker.exists()  # no rename-window, no send-keys
        assert st.clear_flag(tmp_path).exists()  # never consumed

    def test_flag_is_consumed_only_after_a_passing_recheck(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        env = _auto_env(bindir)
        env["VIGIL_CLEAR_DELAY"] = "0.5"
        _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert st.clear_flag(tmp_path).exists()  # during the delay
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]
        assert not st.clear_flag(tmp_path).exists()

    def test_copy_mode_holds(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN, in_mode="1")
        result = _run(STOP, {"cwd": str(tmp_path)}, _auto_env(bindir), tmp_path)
        self._assert_held(tmp_path, result, marker, st, "copy mode")

    def test_missing_tmux_pane_holds_when_armed_in_default_lineage(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TMUX_PANE", raising=False)
        st = _promote_and_arm(tmp_path, None)  # armed under the default lineage
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN)
        env = _auto_env(bindir)
        env.pop("TMUX_PANE")
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        self._assert_held(tmp_path, result, marker, st, "no tmux pane is known")

    def test_vigil_tmux_bin_is_used_for_every_tmux_call(self, tmp_path, monkeypatch):
        st = _promote_and_arm(tmp_path, "%9")
        monkeypatch.setenv("TMUX_PANE", "%9")
        # only `mytmux` exists: a bare `tmux` on PATH would be a failing/absent binary
        bindir, marker = _fake_tmux(tmp_path, SAFE_SCREEN, name="mytmux")
        env = _auto_env(bindir)
        env["PATH"] = f"{bindir}:/usr/bin:/bin"
        env["VIGIL_TMUX_BIN"] = str(bindir / "mytmux")
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0 and result.stdout.strip() == ""
        assert _wait_calls(marker, 1) == ["send-keys -t %9 /clear Enter"]
        seen = (tmp_path / "all-calls").read_text()
        assert "has-session" in seen and "capture-pane" in seen

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

    def test_uses_stdin_session_id_not_sibling_newest_write(self, tmp_path):
        # Regression test for the observed misfire: two live sessions sharing
        # a worktree, sibling's write is newer and over threshold too — the
        # hook must nudge with THIS session's pct, sourced from stdin's
        # session_id, not the sibling's.
        from scripts import state as st
        st.begin(tmp_path)
        store = tmp_path / "census" / "status.json"
        store.parent.mkdir(parents=True, exist_ok=True)
        key = os.path.realpath(str(tmp_path))
        now = time.time()
        store.write_text(json.dumps({
            "sessions": {
                "s-mine": {
                    "worktree_cwd": key,
                    "updated_at": now - 5,
                    "payload": {"context_window": {"used_percentage": 40}},
                },
                "s-sibling": {
                    "worktree_cwd": key,
                    "updated_at": now,  # newer write, would win pre-fix
                    "payload": {"context_window": {"used_percentage": 90}},
                },
            }
        }))
        env = _base_env({"CENSUS_STORE": str(store)})
        result = _run(NUDGE, {"cwd": str(tmp_path), "session_id": "s-mine"}, env, tmp_path)
        assert result.returncode == 0
        assert "additionalContext" in result.stdout
        assert "40%" in result.stdout
        assert "90%" not in result.stdout


class TestPackaging:
    def test_plugin_manifest_valid(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert data["name"] == "vigil"
        # Shape, not a literal: pinning the exact string meant every release
        # bump broke this test (it sat red from v0.2.1 onwards asserting
        # "0.2.0"). What packaging actually requires is that a semver version
        # is PRESENT and well-formed — the value itself is the release's business.
        assert re.fullmatch(r"\d+\.\d+\.\d+", data["version"]), data["version"]

    def test_marketplace_lists_vigil(self):
        mkt = PLUGIN_ROOT.parent.parent / ".claude-plugin" / "marketplace.json"
        data = json.loads(mkt.read_text())
        names = [p["name"] for p in data["plugins"]]
        assert "vigil" in names

    def test_skill_and_command_present(self):
        assert (PLUGIN_ROOT / "skills" / "vigil" / "SKILL.md").exists()
        assert (PLUGIN_ROOT / "commands" / "handover.md").exists()


class TestInterpreterChoice:
    """VG-15: PATH python3 (or VIGIL_PYTHON); never a repo-adjacent .venv."""

    def _shim(self, path, marker):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#!/usr/bin/env bash\necho "$0" >> "{marker}"\nexit 0\n')
        path.chmod(0o755)

    def test_repo_adjacent_venv_is_not_used(self, tmp_path):
        plugin = tmp_path / "a" / "b" / "plugin"
        shutil.copytree(PLUGIN_ROOT, plugin, ignore=shutil.ignore_patterns("__pycache__"))
        marker = tmp_path / "venv-ran"
        self._shim(tmp_path / ".venv" / "bin" / "python", marker)
        for name in ("nudge-hook.sh", "session-start.sh", "stop.sh"):
            env = _base_env({"CLAUDE_PLUGIN_ROOT": str(plugin)})
            _run(plugin / "hooks" / name, {"cwd": str(tmp_path)}, env, tmp_path)
        assert not marker.exists()

    def test_vigil_python_override_is_used_by_every_hook(self, tmp_path):
        marker = tmp_path / "override-ran"
        shim = tmp_path / "py" / "mypython"
        self._shim(shim, marker)
        env = _base_env({"VIGIL_PYTHON": str(shim)})
        for script in (NUDGE, SESSION_START):
            _run(script, {"cwd": str(tmp_path)}, env, tmp_path)
        assert len(marker.read_text().split()) == 2
        # stop.sh only reaches python when armed under tmux; the manual path asks it
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        tmux = fake_bin / "tmux"
        tmux.write_text("#!/usr/bin/env bash\nexit 0\n")
        tmux.chmod(0o755)
        env = _base_env({"VIGIL_PYTHON": str(shim), "TMUX": "/x,1,0",
                         "PATH": f"{fake_bin}:{os.environ['PATH']}", "VIGIL_CLEAR_DELAY": "0"})
        _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        # nudge + session-start + the stop guard + the pane check (which holds: the
        # shim prints nothing, so the pane cannot be read and stop-hook is never reached)
        assert len(marker.read_text().split()) == 4

    def test_bin_vigil_honours_override(self, tmp_path):
        marker = tmp_path / "bin-ran"
        shim = tmp_path / "mypython"
        self._shim(shim, marker)
        env = _base_env({"VIGIL_PYTHON": str(shim)})
        subprocess.run([str(PLUGIN_ROOT / "bin" / "vigil"), "context"], env=env, check=False,
                       capture_output=True, text=True)
        assert marker.exists()

    def test_no_script_probes_for_a_venv(self):
        for name in ("nudge-hook.sh", "session-start.sh", "stop.sh"):
            assert ".venv" not in (PLUGIN_ROOT / "hooks" / name).read_text()
        assert ".venv" not in (PLUGIN_ROOT / "bin" / "vigil").read_text()


class TestNudgeMatcherDocs:
    """VG-2: the docs say what hooks.json does (PostToolUse only on Task tools)."""

    def test_matcher_and_docs_agree(self):
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        assert hooks["PostToolUse"][0]["matcher"] == "TaskCreate|TaskUpdate"
        for doc in (PLUGIN_ROOT / "hooks" / "nudge-hook.sh", PLUGIN_ROOT / "scripts" / "cli.py"):
            text = doc.read_text()
            assert "TaskCreate|TaskUpdate" in text
            assert "after every tool call" not in text


class TestPaneBusy:
    """BUSY is checked only post-delay (busy=True) and only under the box."""

    def test_busy_only_when_asked(self):
        from scripts import pane
        assert pane.hold_reason(BUSY_SCREEN) is None
        assert pane.hold_reason(BUSY_SCREEN, busy=True) == "the session is busy (a turn is running)"

    def test_transcript_text_is_not_the_footer(self):
        from scripts import pane
        assert pane.hold_reason(TRANSCRIPT_MENTIONS_BUSY, busy=True) is None

    def test_named_rule_is_a_rule(self):
        from scripts import pane
        assert pane.hold_reason(NAMED_SCREEN, busy=True) is None
        assert pane.input_row(f"{'─' * 12} not a rule\n❯ x\n") is None
