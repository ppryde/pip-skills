import re
from pathlib import Path

import pytest
import yaml

from scripts.dispatch import ROLES, parse_reply

AGENTS = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "agents"
WRITE_TOOLS = {"Edit", "NotebookEdit"}


def _load(role):
    text = (AGENTS / f"overseer-{role}.md").read_text()
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body


@pytest.mark.parametrize("role", ROLES)
def test_definition_shape(role):
    meta, body = _load(role)
    assert meta["name"] == f"overseer-{role}"
    assert meta["model"] == "sonnet"
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert {"Read", "Write"} <= tools
    assert "Agent" not in tools  # workers never dispatch (no forks, no nesting)
    if role in ("reviewer", "planner", "verifier"):
        assert not tools & WRITE_TOOLS
    assert "ONE line" in body and "25 words" in body


@pytest.mark.parametrize("role", ROLES)
def test_reply_examples_parse(role):
    _, body = _load(role)
    examples = re.findall(r"^`(.+ → /.+/dispatch/.+\.md)`$", body, flags=re.MULTILINE)
    assert examples, role
    for line in examples:
        parse_reply(role, line)
