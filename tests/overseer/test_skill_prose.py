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
    assert json.loads((OVERSEER / ".claude-plugin" / "plugin.json").read_text())["version"] == "0.24.1"


def test_cli_location_and_cheat_sheet_present():
    # Round 2 of WF-113: a benchmark run shelled out to `find / -iname
    # overseer` (120s) because it didn't know where cli.py was, and guessed
    # its way through dispatch-prep/set-section signatures. Both must be
    # answered directly in this file.
    assert "Locate the CLI" in SKILL
    assert "never search the filesystem for it" in SKILL
    assert "scripts/cli.py" in SKILL
    for verb in ("resume", "bootstrap", "dispatch-prep", "set-stage", "set-section",
                 "set-field", "block", "release", "show", "facts --pending"):
        assert f"`{verb}`" in SKILL, verb


def test_locate_the_cli_is_the_first_heading():
    # Round 3: still on turn 2, a benchmark run shelled `find / -maxdepth 2`
    # instead of reading this file to the section that already answers it —
    # this has to be unmissable, so it must be the FIRST ## heading, and must
    # give the literal invocation form (not just prose pointing elsewhere).
    first_heading = SKILL.split("\n## ", 1)[1]
    assert first_heading.startswith("Locate the CLI")
    assert '"<base directory>/../../scripts/cli.py" --root . <verb>' in SKILL


def test_policy_md_not_needed_for_s_or_m():
    # Round 3: still Read policy.md on turn 3 for an S card. It must say,
    # unambiguously, that S/M never need it.
    assert "Skip `policy.md` for S and M" in SKILL or "skip `policy.md` for S and M" in SKILL
    assert "S or M card should need NONE of them" in SKILL


def test_one_call_s_brief_and_advance_documented():
    assert "--brief" in SKILL and "--advance" in SKILL
    assert "--chunk` defaults to `1`" in SKILL or "defaults to 1" in SKILL


def test_foreground_dispatch_documented():
    assert "run_in_background: false" in SKILL
    assert "Never poll" in SKILL or "never poll" in SKILL.lower()


def test_orchestrate_and_ledger_skills_declare_effort():
    import yaml
    for name, text in (("orchestrate", SKILL), ("ledger", LEDGER_SKILL)):
        _, front, _ = text.split("---", 2)
        assert yaml.safe_load(front).get("effort") == "medium", name


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
