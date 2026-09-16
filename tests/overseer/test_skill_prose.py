import json
from pathlib import Path

OVERSEER = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
SKILL = (OVERSEER / "skills" / "orchestrate" / "SKILL.md").read_text()
LOOP = (OVERSEER / "skills" / "orchestrate" / "references" / "review-loop.md").read_text()
IMPL = (OVERSEER / "templates" / "implementer.md").read_text()


def test_orchestrator_rules_present():
    for phrase in ("dispatch-prep", "overseer:overseer-", "never fork", "bootstrap",
                   "facts --pending", "run_in_background", "stage boundary"):
        assert phrase in SKILL, phrase


def test_retired_instructions_gone():
    assert "cadence" not in IMPL
    assert "[peer-cc]" not in SKILL
    assert "log-usage <card> --role" not in SKILL
    assert "log-review <id>" not in LOOP


def test_version_bumped():
    assert json.loads((OVERSEER / ".claude-plugin" / "plugin.json").read_text())["version"] == "0.24.0"
