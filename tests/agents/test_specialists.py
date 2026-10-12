"""The five specialists (planner, implementer, verifier, summariser, researcher) and contract revision 1.1."""
from __future__ import annotations

import copy
import json
import re

import pytest

from conftest import CONTRACT, EXAMPLES, PLUGIN

PAIRS = {"planner": "planner", "implementer": "implementer", "verifier": "verifier", "summariser": "summary",
         "researcher": "research"}
KIND = {"planner": "plan", "implementer": "change", "verifier": "test", "summariser": "summary", "researcher": "research"}


def load_example(stem):
    brief = (EXAMPLES / f"{stem}.brief.txt").read_text()
    msg = (EXAMPLES / f"{stem}.result.md").read_text()
    res = json.loads(re.search(r"^```pip-agents-result\n(.*?)^```", msg, re.M | re.S).group(1))
    return brief, msg, res


def block(res):
    return "```pip-agents-result\n" + json.dumps(res) + "\n```\n"


@pytest.mark.parametrize("persona", sorted(PAIRS))
def test_specialist_examples_pass_every_check(vr, persona):
    brief, msg, _ = load_example(PAIRS[persona])
    _, errs = vr.parse_result(msg, vr.parse_brief(brief), persona)
    assert errs == [], errs


NEGATIVE = {
    "plan_chunks_not_steps": ("planner", lambda r: r["payload"].update(chunks=5), "number of steps"),
    "plan_done_without_steps": ("planner", lambda r: r["payload"].pop("steps"), "lists its steps"),
    "plan_needs_context_without_questions": ("planner", lambda r: r["payload"].update(outcome="needs_context", steps=[], chunks=0),
                                             "questions"),
    "change_done_without_commit": ("implementer", lambda r: r["payload"].update(commits=[]), "names its commits"),
    "change_passed_over_total": ("implementer", lambda r: r["payload"].update(tests_passed=9), "exceeds tests_total"),
    "test_pass_with_failure": ("verifier", lambda r: r["payload"].update(outcome="pass"), "outcome pass"),
    "test_fail_when_green": ("verifier", lambda r: (r["payload"]["gates"][0].update(exit_code=0), r["payload"].pop("failures")),
                             "outcome fail"),
    "test_gate_not_the_briefs_command": ("verifier", lambda r: r["payload"]["gates"][0].update(command="pytest -q"),
                                         "verbatim"),
    "summary_ok_without_points": ("summariser", lambda r: r["payload"].update(points=[]), "at least one point"),
    "summary_long_point": ("summariser", lambda r: r["payload"]["points"][0].update(text="x" * 300), "text"),
    "research_ok_without_sources": ("researcher", lambda r: r["payload"].update(sources=[]), "cites at least one source"),
    "research_unknown_field": ("researcher", lambda r: r["payload"].update(confidence="high"), "unknown field confidence"),
}


@pytest.mark.parametrize("case", sorted(NEGATIVE))
def test_specialist_negative(vr, case):
    persona, fn, want = NEGATIVE[case]
    brief, _, res = load_example(PAIRS[persona])
    res = copy.deepcopy(res)
    fn(res)
    _, errs = vr.parse_result(block(res), vr.parse_brief(brief), persona)
    assert any(want in e for e in errs), (case, errs)


@pytest.mark.parametrize("text, ok", [
    ("brief: pip-agents/1\nkind: plan\nintent: /t/task.md\n", True),
    ("brief: pip-agents/1\nkind: plan\nbundle: /t/b.md\n", True),
    ("brief: pip-agents/1\nkind: plan\n", False),
    ("brief: pip-agents/1\nkind: change\nintent: /t/s.md\ntarget: /t/f.txt\ntests: pytest -q\n", True),
    ("brief: pip-agents/1\nkind: change\ntarget: /t/f.txt\n", False),
    ("brief: pip-agents/1\nkind: test\ntests: pytest -q\n", True),
    ("brief: pip-agents/1\nkind: test\n", False),
    ("brief: pip-agents/1\nkind: summary\ntarget: /t/a.log\n", True),
    ("brief: pip-agents/1\nkind: summary\n", False),
    ("brief: pip-agents/1\nkind: research\ntarget: /t/f.txt\nquestion: Where?\n", True),
    ("brief: pip-agents/1\nkind: research\ntarget: /t/f.txt\n", False),
    ("brief: pip-agents/1\nkind: research\ntarget: /t/f.txt\nquestion: Where?\nlimit: 5\n", False),
    ("brief: pip-agents/1\nkind: review\ntarget: /t/d.patch\nquestion: Where?\n", False),
])
def test_specialist_briefs(vr, text, ok):
    assert (vr.check_brief(vr.parse_brief(text)) == []) is ok, vr.check_brief(vr.parse_brief(text))


def test_new_kinds_registered(vr):
    assert {"summary", "research"} <= set(vr.result_schema()["properties"]["kind"]["enum"])
    pmap = json.loads((CONTRACT / "personas.json").read_text())
    assert {n: pmap[n]["kind"] for n in KIND} == KIND


def test_only_the_implementer_writes():
    for p in (PLUGIN / "agents").glob("*.md"):
        tools = re.search(r"^tools: (.*)$", p.read_text(), re.M).group(1).split(", ")
        has_write = bool({"Edit", "Write"} & set(tools))
        assert has_write is (p.stem == "implementer"), p.stem
        assert not {"Agent", "Skill", "WebFetch", "WebSearch"} & set(tools), p.stem
        assert not any(t.startswith("mcp__") for t in tools), p.stem


def test_implementer_text_matches_its_tools():
    text = (PLUGIN / "agents" / "implementer.md").read_text()
    assert "read-only" not in text and "Write no files" not in text
    assert "Edit only inside the brief's `target:`" in text
    assert "One plain command per Bash call" in text and "use Monitor, not `sleep`" in text
    assert "nothing that writes" not in text.lower()


def test_every_specialist_declares_its_consumer():
    """Each persona has a documented consumer or is explicitly 'library, no consumer yet' in the README table."""
    readme = (PLUGIN / "README.md").read_text()
    for name in ("explorer", *KIND):
        row = next((ln for ln in readme.splitlines() if f"`pip-agents:{name}`" in ln and ln.startswith("|")), None)
        assert row, name
        consumer = row.rstrip("|").split("|")[-1].strip()
        assert consumer, name
        assert consumer.startswith("library, no consumer yet") or "django-inquisition" in consumer, (name, consumer)
