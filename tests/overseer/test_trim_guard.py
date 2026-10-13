"""Context-trim PR: guard rules (WF-284 background dispatch, WF-283 short wrapper)."""
import os
import sys
from pathlib import Path

import pytest
from factories import make_card

from scripts import guard
from scripts.guard import Verdict, bash_check, decide

ROOTS = [Path("/state"), Path("/plugins"), Path("/cfg")]
CARD = make_card("WF-012")


def _agent(subagent_type, **tool_input):
    return {"tool_name": "Agent", "cwd": "/repo",
            "tool_input": {"subagent_type": subagent_type, "prompt": "/state/b.md", **tool_input}}


class TestBackgroundDispatchDenied:
    @pytest.mark.parametrize("agent", [
        "overseer:overseer-planner", "overseer:overseer-implementer", "overseer:overseer-reviewer",
        "overseer:overseer-fixer", "overseer:overseer-verifier",
    ])
    def test_background_overseer_agent_is_denied(self, agent):
        reason = decide(_agent(agent, run_in_background=True), [CARD], ROOTS).deny_reason
        assert reason and "WF-012" in reason and "foreground" in reason

    def test_foreground_is_allowed(self):
        assert decide(_agent("overseer:overseer-reviewer", run_in_background=False), [CARD], ROOTS) == Verdict()
        assert decide(_agent("overseer:overseer-reviewer"), [CARD], ROOTS) == Verdict()

    def test_other_agent_types_may_run_in_background(self):
        assert decide(_agent("general-purpose", run_in_background=True), [CARD], ROOTS) == Verdict()

    def test_no_card_in_flight_means_no_rule(self):
        assert decide(_agent("overseer:overseer-reviewer", run_in_background=True), [], ROOTS) == Verdict()

    def test_tripwire_still_wins(self):
        hot = make_card("WF-012", budget_estimate=100, budget_actual=250)
        reason = decide(_agent("overseer:overseer-fixer", run_in_background=True), [hot], ROOTS).deny_reason
        assert reason.startswith("TRIPWIRE")


class TestShortWrapper:
    def _wrapper(self, state: Path, *, cli: Path | None = None, body: str | None = None) -> Path:
        state.mkdir(parents=True, exist_ok=True)
        path = state / guard.WRAPPER_NAME
        path.write_text(body if body is not None else guard.wrapper_text(
            Path(sys.executable), cli or guard._own_cli(), Path("/some/repo")))
        path.chmod(0o755)
        return path

    def test_wrapper_text_is_what_the_guard_recognises(self, tmp_path):
        wrapper = self._wrapper(tmp_path / "state")
        ok, _ = bash_check(f"{wrapper} resume", roots=[(tmp_path / "state").resolve()], cwd=str(tmp_path))
        assert ok

    def test_wrapper_with_args_and_redirect_is_allowed(self, tmp_path):
        wrapper = self._wrapper(tmp_path / "state")
        roots = [(tmp_path / "state").resolve()]
        ok, _ = bash_check(f"{wrapper} show WF-1 --json 2>&1", roots=roots, cwd=str(tmp_path))
        assert ok

    def test_forged_wrapper_is_denied(self, tmp_path):
        wrapper = self._wrapper(tmp_path / "state", body="#!/bin/sh\nrm -rf \"$HOME\"\n")
        roots = [(tmp_path / "state").resolve()]
        ok, _ = bash_check(f"{wrapper} resume", roots=roots, cwd=str(tmp_path))
        assert not ok

    def test_wrapper_pointing_at_a_foreign_script_is_denied(self, tmp_path):
        evil = tmp_path / "scripts" / "cli.py"
        evil.parent.mkdir()
        evil.write_text("print(1)\n")
        wrapper = self._wrapper(tmp_path / "state", cli=evil)
        roots = [(tmp_path / "state").resolve()]
        ok, _ = bash_check(f"{wrapper} resume", roots=roots, cwd=str(tmp_path))
        assert not ok

    def test_a_file_named_ov_outside_the_state_root_is_denied(self, tmp_path):
        other = tmp_path / "elsewhere"
        wrapper = self._wrapper(other)
        roots = [(tmp_path / "state").resolve()]
        (tmp_path / "state").mkdir()
        ok, _ = bash_check(f"{wrapper} resume", roots=roots, cwd=str(tmp_path))
        assert not ok

    def test_symlinked_wrapper_is_denied(self, tmp_path):
        real = self._wrapper(tmp_path / "elsewhere")
        state = tmp_path / "state"
        state.mkdir()
        (state / guard.WRAPPER_NAME).symlink_to(real)
        ok, _ = bash_check(f"{state / guard.WRAPPER_NAME} resume",
                           roots=[state.resolve()], cwd=str(tmp_path))
        assert not ok

    def test_no_roots_means_no_wrapper(self, tmp_path):
        wrapper = self._wrapper(tmp_path / "state")
        ok, _ = bash_check(f"{wrapper} resume", roots=None, cwd=str(tmp_path))
        assert not ok

    def test_chained_with_a_forbidden_command_is_still_denied(self, tmp_path):
        wrapper = self._wrapper(tmp_path / "state")
        roots = [(tmp_path / "state").resolve()]
        ok, _ = bash_check(f"{wrapper} resume && pytest -q", roots=roots, cwd=str(tmp_path))
        assert not ok
