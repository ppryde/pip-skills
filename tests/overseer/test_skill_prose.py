import json
from pathlib import Path

OVERSEER = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
SKILL = (OVERSEER / "skills" / "orchestrate" / "SKILL.md").read_text()
LOOP = (OVERSEER / "skills" / "orchestrate" / "references" / "review-loop.md").read_text()
IMPL = (OVERSEER / "templates" / "implementer.md").read_text()
LEDGER_SKILL = (OVERSEER / "skills" / "ledger" / "SKILL.md").read_text()


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


def test_ledger_skill_qualifies_manual_logging_verbs():
    # The Progress and Reviews bullets must not tell the orchestrator to
    # log-progress/log-review after every dispatched unit of work or review
    # round — under orchestration the report hook does that automatically.
    # Both bullets must say so.
    progress_bullet = LEDGER_SKILL.split("**Progress:**", 1)[1].split("- **", 1)[0]
    assert "log-progress" in progress_bullet
    assert "report hook" in progress_bullet
    assert "automatically" in progress_bullet

    reviews_bullet = LEDGER_SKILL.split("**Reviews:**", 1)[1].split("- **", 1)[0]
    assert "log-review" in reviews_bullet
    assert "report hook" in reviews_bullet
    assert "automatically" in reviews_bullet
