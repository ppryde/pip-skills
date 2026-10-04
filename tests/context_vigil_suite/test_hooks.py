from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from context_vigil import config, hooks, paths, session, state

from .test_context_window import _ingest


def _payload(repo: Path, **extra: object) -> dict:
    return {"cwd": str(repo), "session_id": "s1", **extra}


def _over(repo: Path, pct: float = 80) -> None:
    _ingest(repo, "s1", pct)


@pytest.fixture
def fake_tmux(iso: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmux stub that logs its argv; has-session succeeds."""
    log = iso / "tmux.log"
    stub = iso / "tmux"
    stub.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("CONTEXT_VIGIL_CLEAR_DELAY", "0")
    monkeypatch.setenv("CONTEXT_VIGIL_KICK_DELAY", "0")
    return log


def _wait_for(path: Path, text: str) -> str:
    for _ in range(50):
        if path.exists() and text in path.read_text():
            return path.read_text()
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {path}")


# --- nudge -------------------------------------------------------------------

def test_nudge_fires_once_over_threshold(repo: Path) -> None:
    _over(repo)
    out = hooks.nudge(_payload(repo, hook_event_name="UserPromptSubmit"))
    assert out is not None
    body = json.loads(out)["hookSpecificOutput"]
    assert body["hookEventName"] == "UserPromptSubmit"
    assert "80%" in body["additionalContext"]
    assert str(paths.launcher_path()) in body["additionalContext"]
    assert hooks.nudge(_payload(repo)) is None  # gate holds


def test_nudge_repeats_every_repeat_step(repo: Path) -> None:
    payload = _payload(repo, hook_event_name="PostToolUse")
    _over(repo, 35)
    assert hooks.nudge(payload) is not None
    _over(repo, 38)
    assert hooks.nudge(payload) is None        # under last + 5
    _over(repo, 40)
    assert hooks.nudge(payload) is not None    # last + 5 reached
    _over(repo, 42)
    assert hooks.nudge(payload) is None
    assert session.load("s1")["last_nudged_pct"] == 40


def test_nudge_repeat_step_is_configurable(repo: Path) -> None:
    config.set_value(repo, "nudge.repeat_step", "2")
    _over(repo, 40)
    assert hooks.nudge(_payload(repo)) is not None
    _over(repo, 41)
    assert hooks.nudge(_payload(repo)) is None
    _over(repo, 42)
    assert hooks.nudge(_payload(repo)) is not None


def test_new_cycle_resets_the_repeat_sequence(repo: Path) -> None:
    _over(repo, 50)
    assert hooks.nudge(_payload(repo)) is not None
    state.begin_cycle(paths.scope_dir(repo))
    assert hooks.nudge(_payload(repo)) is not None   # same %, fresh cycle


def test_nudge_without_session_id_fires_once_per_cycle(repo: Path) -> None:
    _over(repo, 50)
    _ingest(repo, "x", 50)
    payload = {"cwd": str(repo)}
    assert hooks.nudge(payload) is not None
    _over(repo, 90)
    _ingest(repo, "x", 90)
    assert hooks.nudge(payload) is None


def test_nudge_silent_under_threshold(repo: Path) -> None:
    _over(repo, 10)
    assert hooks.nudge(_payload(repo)) is None


def test_nudge_respects_configured_threshold(repo: Path) -> None:
    _over(repo, 50)
    config.set_value(repo, "context.threshold", "60")
    assert hooks.nudge(_payload(repo)) is None
    config.set_value(repo, "context.threshold", "45")
    assert hooks.nudge(_payload(repo)) is not None


def test_nudge_silent_when_paused_or_cooling(repo: Path) -> None:
    _over(repo)
    scope = paths.scope_dir(repo)
    state.pause(scope)
    assert hooks.nudge(_payload(repo)) is None
    state.resume(scope)
    state.begin_cycle(scope, cooldown=True)
    assert hooks.nudge(_payload(repo)) is None


def test_nudge_remote_mode_mentions_inline(repo: Path) -> None:
    _over(repo)
    config.set_value(repo, "context.mode", "remote")
    out = hooks.nudge(_payload(repo))
    assert out is not None and "--inline" in out


# --- stop --------------------------------------------------------------------

def test_stop_manual_is_loud_and_keeps_flag(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    out = hooks.stop(_payload(repo))
    assert out is not None and "type /clear" in json.loads(out)["systemMessage"]
    assert state.clear_requested(scope)


def test_stop_silent_when_unarmed(repo: Path) -> None:
    assert hooks.stop(_payload(repo)) is None


def test_stop_auto_sends_clear(repo: Path, fake_tmux: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    assert hooks.stop(_payload(repo)) is None
    assert not state.clear_requested(scope)
    assert "send-keys -t %7 /clear Enter" in _wait_for(fake_tmux, "/clear")


def test_stop_dead_tmux_server_falls_back_to_manual(repo: Path, iso: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    stub = iso / "deadtmux"
    stub.write_text('#!/usr/bin/env bash\n[ "$1" = has-session ] && exit 1\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    out = hooks.stop(_payload(repo))
    assert out is not None and "type /clear" in out
    assert state.clear_requested(scope)


# --- session start -----------------------------------------------------------

def test_session_start_injects_once_with_preamble(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "THE HANDOVER")
    out = hooks.session_start(_payload(repo, source="clear"))
    assert out is not None
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("Resume from this handover.") and "THE HANDOVER" in ctx
    assert hooks.session_start(_payload(repo, source="clear")) is None
    assert list(state.handoff_archive_dir(scope).iterdir())


def test_session_start_kicks_only_on_clear(repo: Path, fake_tmux: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "## Goal\nShip it.\n")
    hooks.session_start(_payload(repo, source="startup"))
    time.sleep(0.3)
    assert not fake_tmux.exists() or "send-keys" not in fake_tmux.read_text()
    hooks.session_start(_payload(repo, source="clear"))
    assert "Next Step" in _wait_for(fake_tmux, "send-keys")


def test_startup_with_waiting_handover_only_notifies(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "# Handover\n\n## Goal\nShip the installer.\n")
    out = hooks.session_start(_payload(repo, source="startup"))
    assert out is not None
    data = json.loads(out)
    assert "Ship the installer." in data["systemMessage"]
    assert "resume the handover" in data["systemMessage"]
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "NOT been loaded" in ctx and "--resume" in ctx
    assert "Resume from this handover" not in out
    assert state.read_handoff(scope) is not None  # still waiting, not archived


def test_startup_without_handover_is_silent(repo: Path) -> None:
    assert hooks.session_start(_payload(repo, source="startup")) is None


def test_resume_source_also_only_notifies(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    out = hooks.session_start(_payload(repo, source="resume"))
    assert out is not None and "systemMessage" in json.loads(out)
    assert state.read_handoff(scope) == "doc"


@pytest.mark.parametrize("named_session, tmux_env", [
    pytest.param(None, "/tmp/tmux-501/default,1,0", id="tmux_sessions"),
    pytest.param("cc-repo-1", "/tmp/tmux-501/claude,1,0", id="named_session_two_panes"),
])
def test_two_panes_keep_separate_scopes(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                        named_session, tmux_env: str) -> None:
    if named_session:
        monkeypatch.setenv("CONTEXT_VIGIL_SESSION", named_session)
    monkeypatch.setenv("TMUX", tmux_env)
    monkeypatch.setenv("TMUX_PANE", "%1")
    state.request_clear(paths.scope_dir(repo), "PANE ONE")
    monkeypatch.setenv("TMUX_PANE", "%2")
    assert hooks.session_start(_payload(repo, source="clear")) is None
    monkeypatch.setenv("TMUX_PANE", "%1")
    out = hooks.session_start(_payload(repo, source="clear"))
    assert out is not None and "PANE ONE" in out


def test_session_start_opens_a_new_cycle(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.set_gate(scope)
    hooks.session_start(_payload(repo, source="clear"))
    assert not state.gate_active(scope)


@pytest.mark.parametrize("source", ["startup", "resume", "compact"])
def test_cooldown_does_not_start_on_startup_or_resume(repo: Path, source: str) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "WAITING")
    hooks.session_start(_payload(repo, source=source))
    assert not state.cooldown_active(scope, 60)
    _over(repo)
    assert hooks.nudge(_payload(repo)) is not None


def test_bare_clear_with_no_handover_starts_no_cooldown(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    hooks.session_start(_payload(repo, source="clear"))
    assert not state.cooldown_active(scope, 60)


def test_cooldown_starts_when_a_clear_loaded_a_handover(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "DOC")
    assert hooks.session_start(_payload(repo, source="clear")) is not None
    assert state.cooldown_active(scope, 60)
    _over(repo)
    assert hooks.nudge(_payload(repo)) is None          # nudges suppressed ...
    assert state.request_clear(scope, "NEXT") == "armed"  # ... an explicit handover is not


def test_cooldown_length_follows_config(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "DOC")
    hooks.session_start(_payload(repo, source="clear"))
    config.set_value(repo, "handover.cooldown_seconds", "0")
    _over(repo)
    assert hooks.nudge(_payload(repo)) is not None


def test_session_scoping(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-1")
    state.request_clear(paths.scope_dir(repo), "MINE")
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-2")
    assert hooks.session_start(_payload(repo, source="clear")) is None


def test_hook_and_cli_share_a_scope_across_subdirectories(repo: Path, run_cli) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
    sub = repo / "pkg" / "api"
    sub.mkdir(parents=True)
    notes = repo.parent / "notes.md"   # never inside the repository
    notes.write_text("## Failed Attempts\nNone\n\n## Next Step\ngo\n")
    result = run_cli("handover", "--file", str(notes), "--no-snapshot", cwd=sub)
    assert result.returncode == 0, result.stderr
    assert state.clear_requested(paths.scope_dir(repo))
    out = hooks.stop({"cwd": str(repo), "session_id": "s1"})
    assert out is not None and "Handover saved" in json.loads(out)["systemMessage"]


def test_headless_child_never_touches_the_parent_scope_or_tmux(
        repo: Path, fake_tmux: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-1")   # inherited from the parent
    parent = paths.scope_dir(repo)
    state.request_clear(parent, "PARENT HANDOFF")
    state.set_gate(parent)
    before = sorted(p.name for p in parent.iterdir())
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    child = {"cwd": str(repo), "session_id": "child"}
    assert hooks.session_start({**child, "source": "startup"}) is None
    assert hooks.session_start({**child, "source": "clear"}) is None
    assert hooks.stop(child) is None
    _over(repo)
    _ingest(repo, "child", 80)
    hooks.nudge({**child, "hook_event_name": "PostToolUse"})
    assert sorted(p.name for p in parent.iterdir()) == before
    assert state.read_handoff(parent) == "PARENT HANDOFF"
    assert not fake_tmux.exists()
    assert paths.headless_scope(repo, "child").is_dir()


def test_headless_by_record_also_skips_tmux(repo: Path, fake_tmux: Path) -> None:
    record = session.blank()
    record["headless"] = True
    session.save("child", record)
    own = paths.headless_scope(repo, "child")
    state.request_clear(own, "doc")
    assert hooks.stop({"cwd": str(repo), "session_id": "child"}) is None
    assert state.clear_requested(own) and not fake_tmux.exists()


# --- run / launcher ----------------------------------------------------------

def test_run_never_raises_on_garbage() -> None:
    assert hooks.run("nudge", "not json") is None
    assert hooks.run("bogus", "{}") is None


def test_launcher_hook_round_trip(run_cli, repo: Path) -> None:
    state.request_clear(paths.scope_dir(repo), "VIA LAUNCHER")
    result = run_cli("hook", "session-start", stdin=json.dumps(_payload(repo, source="clear")))
    assert result.returncode == 0
    assert "VIA LAUNCHER" in result.stdout


def test_default_tmux_is_inert(repo: Path, iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from context_vigil import tmux

    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    sent: list = []
    monkeypatch.setattr(tmux, "send_detached", lambda *a, **k: sent.append(a))
    state.request_clear(paths.scope_dir(repo), "WAITING")
    assert not tmux.reachable()
    out = hooks.session_start(_payload(repo, source="clear"))
    assert out is not None and "WAITING" in out
    assert sent == []


def _nudge_text(repo: Path, event: str) -> str:
    _over(repo)
    out = hooks.nudge(_payload(repo, hook_event_name=event))
    assert out is not None
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_nudge_on_user_prompt_asks_before_handing_over(repo: Path) -> None:
    text = _nudge_text(repo, "UserPromptSubmit")
    assert "Answer the user's message first" in text
    assert "ASK whether to hand over now" in text
    assert "Do not run `handover` until they agree" in text
    assert "80%" in text
    assert "subagent" not in text


def test_nudge_on_post_tool_use_hands_over_unattended(repo: Path) -> None:
    text = _nudge_text(repo, "PostToolUse")
    assert "subagent" in text and "handover --file" in text
    assert "ASK whether" not in text


def test_nudge_unknown_event_is_unattended(repo: Path) -> None:
    assert "handover --file" in _nudge_text(repo, "Whatever")


def test_clear_delay_defaults_to_two_seconds(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from context_vigil import tmux
    monkeypatch.delenv("CONTEXT_VIGIL_CLEAR_DELAY", raising=False)
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%1")
    sent = []
    monkeypatch.setattr(tmux, "reachable", lambda: True)
    monkeypatch.setattr(tmux, "send_detached", lambda t, keys, delay: sent.append(delay))
    state.request_clear(paths.scope_dir(repo), "H")
    hooks.stop({"cwd": str(repo)})
    assert sent == ["2"]
