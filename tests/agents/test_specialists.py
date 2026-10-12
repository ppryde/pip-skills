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


# ---- the rules lens additions of the adoption bundle: `exceptions:` and `exception` ----------------------------

RULES_BRIEF = "brief: pip-agents/1\nkind: review\nref: ddd-1of2\ntarget: /t/scope.txt\nrules: /r/ddd.md L1-40,L90-99 (DDD-001,DDD-002)\n"


def rules_result(**finding):
    f = {"id": "DDD-001", "rule": "r", "file": "/t/a.py", "line": 3, "severity": "critical", "category": "c", "claim": "c",
         "evidence": "e", "fix": "f"}
    f.update(finding)
    return {"result": "pip-agents/1", "kind": "review", "persona": "reviewer-rules", "ref": "ddd-1of2", "status": "ok",
            "summary": "s", "checked": ["/t/a.py"], "unchecked": [], "out_of_lens": [], "injection_attempts": [],
            "payload": {"lens": "rules", "findings": [f], "medium": [], "rules_checked": "2/2", "n_a": []}}


def test_exception_field_needs_the_report_flag(vr):
    res = rules_result(exception="Test doubles may import infrastructure")
    _, errs = vr.parse_result(block(res), vr.parse_brief(RULES_BRIEF), "reviewer-rules")
    assert any("exceptions: report" in e for e in errs), errs
    _, errs = vr.parse_result(block(res), vr.parse_brief(RULES_BRIEF + "exceptions: report\n"), "reviewer-rules")
    assert errs == [], errs


def test_exceptions_key_is_review_only_and_enumerated(vr):
    assert vr.check_brief(vr.parse_brief(RULES_BRIEF + "exceptions: skip\n")) == []
    assert vr.check_brief(vr.parse_brief(RULES_BRIEF + "exceptions: maybe\n"))
    assert vr.check_brief(vr.parse_brief("brief: pip-agents/1\nkind: summary\ntarget: /t/a\nexceptions: report\n"))


def test_exception_is_a_rules_lens_field_only(vr):
    brief = "brief: pip-agents/1\nkind: review\nref: ddd-1of2\ntarget: /t/a.py\nexceptions: report\n"
    res = rules_result(exception="x")
    res["persona"], res["payload"]["lens"] = "reviewer-scope", "scope"
    del res["payload"]["rules_checked"], res["payload"]["n_a"]
    _, errs = vr.parse_result(block(res), vr.parse_brief(brief), "reviewer-scope")
    assert any("belongs to lens rules" in e for e in errs), errs
