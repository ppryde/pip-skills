"""Last light: prompt classification, the tick's gates, and the loop locks."""
from __future__ import annotations

import json
import threading
import time as _time
from pathlib import Path

import pytest
from context_vigil import hooks, last_light, paths, session, state


def _prompt(repo: Path, text: str, sid: str = "s1") -> dict:
    return {"cwd": str(repo), "session_id": sid, "hook_event_name": "UserPromptSubmit",
            "prompt": text}


@pytest.mark.parametrize("text,kind", [
    ("fix the bug", "human"),
    (last_light.MARKER + " The prompt cache expires…", "ours"),
    (hooks.KICK_PROMPT, "ours"),
    ("<task-notification>\n<task-id>b1</task-id>", "background"),
    ("", "human"),
])
def test_classify_prompt(repo: Path, text: str, kind: str) -> None:
    assert hooks.classify_prompt(_prompt(repo, text)) == kind


def test_human_prompt_arms_and_discards_prepared(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.write_prepared(scope, "# prepared\n", 20)
    hooks.nudge(_prompt(repo, "carry on"))
    assert session.load("s1")["last_light_armed"] is True
    assert not state.is_prepared(scope)


def test_our_prompt_neither_arms_nor_nudges(repo: Path) -> None:
    out = hooks.nudge(_prompt(repo, last_light.MARKER + " prepare"))
    assert out is None
    assert session.load("s1")["last_light_armed"] is False


def test_background_prompt_neither_discards_nor_arms(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.write_prepared(scope, "# prepared\n", 20)
    hooks.nudge(_prompt(repo, "<task-notification>\n<status>completed</status>"))
    assert state.is_prepared(scope)
    assert session.load("s1")["last_light_armed"] is False


def test_post_tool_use_never_arms(repo: Path) -> None:
    hooks.nudge({"cwd": str(repo), "session_id": "s1", "hook_event_name": "PostToolUse"})
    assert session.load("s1")["last_light_armed"] is False

NOW = 1_800_000_000.0
IDLE_SCREEN = "─" * 40 + "\n❯\xa0\x1b[2mTry it\x1b[0m\n" + "─" * 40 + "\n"


@pytest.fixture
def lit(repo: Path, iso: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Last light on, inside a stub tmux whose pane is an idle prompt box; returns the
    keystroke log."""
    monkeypatch.setenv("CONTEXT_VIGIL_LAST_LIGHT", "on")
    log, shot = iso / "tmux.log", iso / "shot.txt"
    shot.write_text(IDLE_SCREEN)
    stub = iso / "tmux"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = capture-pane ]; then cat "{shot}"; exit 0; fi\n'
        f'echo "$@" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    return log


def _arm(sid: str = "s1") -> None:
    record = session.load(sid)
    record["last_light_armed"] = True
    session.save(sid, record)


def _tick_payload(repo: Path, pct: float = 40, left: float = 200, ttl: str = "1h",
                  warm: bool = True, sid: str = "s1") -> dict:
    return {"session_id": sid, "cwd": str(repo),
            "workspace": {"current_dir": str(repo)},
            "context_window": {"used_percentage": pct},
            "prompt_cache": {"warm": warm, "ttl": ttl, "expires_at": NOW + left}}


def _typed(log: Path) -> str:
    for _ in range(50):
        if log.exists() and last_light.MARKER in log.read_text():
            return log.read_text()
        _time.sleep(0.05)
    return log.read_text() if log.exists() else ""


def test_fires_once_when_every_gate_holds(repo: Path, lit: Path) -> None:
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    assert last_light.MARKER in _typed(lit)
    assert session.load("s1")["last_light_armed"] is False


@pytest.mark.parametrize("kwargs,reason", [
    ({"ttl": "5m"}, "no-cache"), ({"warm": False}, "no-cache"),
    ({"left": 301}, "not-near"), ({"left": 0}, "not-near"), ({"left": -5}, "not-near"),
    ({"pct": 24}, "below"),
])
def test_gates(repo: Path, lit: Path, kwargs: dict, reason: str) -> None:
    _arm()
    assert last_light.tick(_tick_payload(repo, **kwargs), now=NOW) == reason


def test_off_by_default(repo: Path, lit: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_VIGIL_LAST_LIGHT")
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "off"


@pytest.mark.parametrize("cache", [None, "nope", {"ttl": "1h", "warm": True},
                                   {"ttl": "1h", "warm": True, "expires_at": "soon"}])
def test_odd_prompt_cache_does_nothing(repo: Path, lit: Path, cache: object) -> None:
    _arm()
    payload = _tick_payload(repo)
    payload["prompt_cache"] = cache
    assert last_light.tick(payload, now=NOW) == "no-cache"


def test_disarmed_until_a_human_prompt(repo: Path, lit: Path) -> None:
    assert last_light.tick(_tick_payload(repo), now=NOW) == "disarmed"


def test_pending_paused_and_unsafe(repo: Path, lit: Path, iso: Path) -> None:
    scope = paths.scope_dir(repo)
    _arm()
    state.pause(scope)
    assert last_light.tick(_tick_payload(repo), now=NOW) == "paused"
    state.resume(scope)
    state.request_clear(scope, "# real\n")
    assert last_light.tick(_tick_payload(repo), now=NOW) == "pending"
    state.consume_handoff(scope)
    state.begin_cycle(scope)
    (iso / "shot.txt").write_text("─" * 40 + "\n❯\xa0half-typed message\n")
    assert last_light.tick(_tick_payload(repo), now=NOW) == "unsafe"


def test_no_tmux(repo: Path, lit: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX")
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "no-tmux"


def _loop_cycle(repo: Path, now: float) -> dict:
    """After a fire: the agent's marked turn refreshes the cache for another hour."""
    hooks.nudge(_prompt(repo, last_light.MARKER + " prepare"))
    return _tick_payload(repo, left=200 + (now - NOW))


def test_loop_both_locks(repo: Path, lit: Path) -> None:
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    state.write_prepared(paths.scope_dir(repo), "# prepared\n", 20)
    later = NOW + 3300
    assert last_light.tick(_loop_cycle(repo, later), now=later) != "fired"


def test_loop_lock2_alone_holds(repo: Path, lit: Path) -> None:
    """Lock 1 forced open: armed stays true; the prepared handover alone stops it."""
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    state.write_prepared(paths.scope_dir(repo), "# prepared\n", 20)
    _arm()                                              # lock 1 broken
    assert last_light.tick(_loop_cycle(repo, NOW + 3300), now=NOW + 3300) == "prepared"


def test_loop_lock1_alone_holds(repo: Path, lit: Path) -> None:
    """Lock 2 forced open: no prepared handover was written; disarm alone stops it."""
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    assert last_light.tick(_loop_cycle(repo, NOW + 3300), now=NOW + 3300) == "disarmed"


def test_concurrent_ticks_fire_once(repo: Path, lit: Path) -> None:
    _arm()
    results: list = []
    threads = [threading.Thread(
        target=lambda: results.append(last_light.tick(_tick_payload(repo), now=NOW)))
        for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("fired") == 1


def test_ingest_cli_runs_the_tick(run_cli, repo: Path, lit: Path) -> None:
    _arm()
    payload = _tick_payload(repo, left=200)
    payload["prompt_cache"]["expires_at"] = _time.time() + 200
    env = {"CONTEXT_VIGIL_LAST_LIGHT": "on", "TMUX": "/tmp/fake,1,0", "TMUX_PANE": "%7"}
    assert run_cli("ingest", stdin=json.dumps(payload), cwd=repo, env=env).returncode == 0
    assert last_light.MARKER in _typed(lit)
