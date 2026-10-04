"""The end-of-turn notice: user-only, once per step, hostile-input safe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from context_vigil import hooks, messages, session

from .conftest import LAUNCHER, cli_env
from .test_context_window import _ingest


def _stop(repo: Path, **extra: object) -> dict:
    return {"cwd": str(repo), "session_id": "s1", "hook_event_name": "Stop", **extra}


def _confident(repo: Path, pct: float) -> None:
    _ingest(repo, "s1", pct, size=200000, model="claude-haiku-4-5")


def test_no_notice_below_threshold(repo: Path) -> None:
    _confident(repo, 20)
    assert hooks.stop(_stop(repo)) is None


def test_first_notice_then_silent_until_next_step(repo: Path) -> None:
    _confident(repo, 41)
    out = json.loads(hooks.stop(_stop(repo)))
    assert out == {"systemMessage": messages.NOTICE_FIRST.format(pct=41, threshold=35)}
    assert session.load("s1")["last_noticed_pct"] == 41
    _confident(repo, 44)
    assert hooks.stop(_stop(repo)) is None
    _confident(repo, 46)
    out = json.loads(hooks.stop(_stop(repo)))
    assert out["systemMessage"] == messages.NOTICE_REPEAT.format(pct=46, threshold=35)


def test_silent_when_stop_hook_active(repo: Path) -> None:
    _confident(repo, 60)
    assert hooks.stop(_stop(repo, stop_hook_active=True)) is None


def test_never_blocks(repo: Path) -> None:
    _confident(repo, 60)
    out = json.loads(hooks.stop(_stop(repo)))
    assert set(out) == {"systemMessage"}


@pytest.mark.parametrize("hostile", ['"; rm -rf ~ #', "line\nbreak", "back\\slash",
                                     "nul\x00byte", "🕯️" * 50, "x" * 10_000])
def test_stop_output_is_one_json_object_for_hostile_payloads(repo: Path, hostile: str) -> None:
    _confident(repo, 70)
    payload = _stop(repo, transcript_path=hostile, extra_field=hostile)
    out = hooks.run("stop", json.dumps(payload))
    if out is not None:
        data = json.loads(out)
        assert set(data) == {"systemMessage"}
        assert len(data["systemMessage"]) <= messages.MAX_LEN


def test_launcher_stop_exits_zero_with_empty_stdout_on_garbage(repo: Path) -> None:
    r = subprocess.run(["bash", str(LAUNCHER), "hook", "stop"], input="{not json",
                       capture_output=True, text=True, env=cli_env(), cwd=repo, timeout=30, check=False)
    assert r.returncode == 0 and r.stdout == ""


def test_next_prompt_gets_the_noticed_context(repo: Path) -> None:
    _confident(repo, 41)
    hooks.stop(_stop(repo))
    out = hooks.nudge({"cwd": str(repo), "session_id": "s1",
                       "hook_event_name": "UserPromptSubmit", "prompt": "hand over"})
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "already been shown" in context
