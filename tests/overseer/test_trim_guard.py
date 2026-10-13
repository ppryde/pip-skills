"""Context-trim PR: guard rules (WF-284 background dispatch)."""
from pathlib import Path

import pytest
from factories import make_card

from scripts.guard import Verdict, decide

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
