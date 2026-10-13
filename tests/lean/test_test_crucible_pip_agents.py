"""WF-270 adoption G: test-crucible's Phase 6 reviewer is pip-agents:reviewer-correctness."""
import json
import re

from lean_common import REPO, read_lf

PLUGIN = REPO / "plugins/test-crucible"
SKILL = PLUGIN / "skills/test-suite-health"
PERSONAS = json.loads((REPO / "plugins/pip-agents/contract/personas.json").read_text())


def _text():
    return read_lf(SKILL / "SKILL.md") + read_lf(SKILL / "references/phase-6-review.md")


def test_declares_pip_agents_dependency_and_bumps_version():
    plugin = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    assert plugin["dependencies"] == ["pip-agents"]
    assert plugin["version"] == "0.3.1"


def test_persona_reference_resolves_to_a_review_persona_with_bash():
    assert PERSONAS["reviewer-correctness"]["kind"] == "review"
    agent = read_lf(REPO / "plugins/pip-agents/agents/reviewer-correctness.md")
    tools = [ln for ln in agent.split("\n") if ln.startswith("tools:")][0]
    assert "Bash" in tools  # risk R5: the reviewer must be able to run the suite
    assert "pip-agents:reviewer-correctness" in _text()


def _brief():
    ref = read_lf(SKILL / "references/phase-6-review.md")
    block = ref.split("```\nbrief: pip-agents/1", 1)[1].split("```", 1)[0]
    lines = ("brief: pip-agents/1" + block).strip().split("\n")
    return ref, dict(ln.split(": ", 1) for ln in lines)


def test_dispatch_brief_conforms_to_the_contract_schema():
    schema = json.loads((REPO / "plugins/pip-agents/contract/brief.schema.json").read_text())
    _, brief = _brief()
    assert set(brief) <= set(schema["properties"])
    assert {"brief", "kind", "target"} <= set(brief)  # kind review requires target
    assert brief["brief"] == "pip-agents/1" and brief["kind"] == "review"
    assert re.fullmatch(schema["properties"]["ref"]["pattern"], brief["ref"])


def test_brief_only_uses_fields_the_correctness_lens_reads():
    lens = read_lf(REPO / "plugins/pip-agents/personas/lenses/correctness.md")
    uses = [ln for ln in lens.split("\n") if ln.startswith("Uses `target:`")][0]
    _, brief = _brief()
    for key in set(brief) - {"brief", "kind", "ref"}:
        assert f"`{key}:`" in uses, key
    flat = " ".join(read_lf(SKILL / "references/phase-6-review.md").split())
    assert 'heading "Claims to refute"' in flat and "there is no `claims:` line" in flat


def test_tests_line_is_a_single_plain_command_the_persona_can_run():
    ref, _ = _brief()
    flat = " ".join(ref.split())
    for needle in ("ONE plain command", "no pipe", "redirect", "`time`", "`cd`",
                   "cannot write files", "pip-agents-result", "`model`", "unchecked", "medium"):
        assert needle in flat, needle
    # the persona's own Bash rule is what the guidance must stay inside
    persona = read_lf(REPO / "plugins/pip-agents/agents/reviewer-correctness.md")
    assert "no pipes" in persona and "redirects" in persona


def test_inline_fallback_is_reported_not_silent():
    flat = " ".join(read_lf(SKILL / "references/phase-6-review.md").split())
    assert "tell the user the subagent review failed" in flat
    assert "state in the report that Phase 6 was inline" in flat


def test_no_general_purpose_fallback_in_the_skill():
    for p in SKILL.rglob("*.md"):
        assert "general-purpose" not in read_lf(p), p
    assert "general-purpose" not in read_lf(PLUGIN / "README.md")


def test_phase_6_reads_the_reference_and_skill_stays_in_budget():
    text = read_lf(SKILL / "SKILL.md")
    assert "references/phase-6-review.md" in text
    assert len(text.encode()) <= 12288
