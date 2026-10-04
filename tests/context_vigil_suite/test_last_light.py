"""Last light: prompt classification, the tick's gates, and the loop locks."""
from __future__ import annotations

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
