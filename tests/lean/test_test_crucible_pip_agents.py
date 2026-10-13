"""WF-270 adoption G: test-crucible's Phase 6 reviewer is pip-agents:reviewer-correctness."""
import json

from lean_common import REPO, read_lf

PLUGIN = REPO / "plugins/test-crucible"
SKILL = PLUGIN / "skills/test-suite-health"
PERSONAS = json.loads((REPO / "plugins/pip-agents/contract/personas.json").read_text())


def _text():
    return read_lf(SKILL / "SKILL.md") + read_lf(SKILL / "references/phase-6-review.md")


def test_declares_pip_agents_dependency_and_bumps_version():
    plugin = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    assert plugin["dependencies"] == ["pip-agents"]
    assert plugin["version"] == "0.3.0"


def test_persona_reference_resolves_to_a_review_persona_with_bash():
    assert PERSONAS["reviewer-correctness"]["kind"] == "review"
    agent = read_lf(REPO / "plugins/pip-agents/agents/reviewer-correctness.md")
    tools = [ln for ln in agent.split("\n") if ln.startswith("tools:")][0]
    assert "Bash" in tools  # risk R5: the reviewer must be able to run the suite
    assert "pip-agents:reviewer-correctness" in _text()


def test_dispatch_uses_a_brief_of_paths_and_the_users_model():
    ref = read_lf(SKILL / "references/phase-6-review.md")
    for needle in ("brief: pip-agents/1", "kind: review", "target:", "intent:", "claims:",
                   "context:", "tests:", "pip-agents-result", "`model`"):
        assert needle in ref, needle
    assert "last ```pip-agents-result" in ref
    assert "unchecked" in ref and "medium" in ref


def test_no_general_purpose_fallback_in_the_skill():
    for p in SKILL.rglob("*.md"):
        assert "general-purpose" not in read_lf(p), p
    assert "general-purpose" not in read_lf(PLUGIN / "README.md")


def test_phase_6_reads_the_reference_and_skill_stays_in_budget():
    text = read_lf(SKILL / "SKILL.md")
    assert "references/phase-6-review.md" in text
    assert len(text.encode()) <= 12288
