import re
from pathlib import Path

import pytest
import yaml

from scripts.dispatch import ROLES
from scripts.schemas import parse_report_message

AGENTS = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "agents"
WRITE_TOOLS = {"Edit", "NotebookEdit"}
# Team default (docs/superpowers/specs/2026-09-16-overseer-token-economy-design.md):
# reviewer/planner carry more judgement, kept at medium; implementer/fixer/verifier
# are mechanical enough for low (confirmed honoured on Claude Code 2.1.273).
EXPECTED_EFFORT = {
    "reviewer": "medium",
    "planner": "medium",
    "implementer": "low",
    "fixer": "low",
    "verifier": "low",
}


def _load(role):
    text = (AGENTS / f"overseer-{role}.md").read_text()
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body


@pytest.mark.parametrize("role", ROLES)
def test_definition_shape(role):
    meta, body = _load(role)
    assert meta["name"] == f"overseer-{role}"
    assert meta["model"] == "sonnet"
    assert meta["effort"] == EXPECTED_EFFORT[role]
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert {"Read", "Write"} <= tools
    assert "Agent" not in tools  # workers never dispatch (no forks, no nesting)
    if role in ("reviewer", "planner", "verifier"):
        assert not tools & WRITE_TOOLS
    assert "```overseer-report" in body
    assert "no narration" in body.lower()


@pytest.mark.parametrize("role", ROLES)
def test_reply_example_parses(role):
    _, body = _load(role)
    match = re.search(r"```overseer-report\n(.+?)\n```", body, flags=re.DOTALL)
    assert match, f"no overseer-report example in overseer-{role}.md"
    example_message = f"```overseer-report\n{match.group(1)}\n```"
    report = parse_report_message(role, example_message)
    assert report.card and report.stage
