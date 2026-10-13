"""WF-283: the short overseer-report block. The hook reads card, stage, round,
slot and chunk off the detail path; the long form still parses identically."""
import json
import re
from pathlib import Path

import pytest

from scripts import schemas
from scripts.report_hook import EXPECTED_SHAPE
from scripts.schemas import ReportError, parse_report, parse_report_message

D = "/x/state/dispatch/WF-12"
AGENTS = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "agents"
IDENTITY = {"schema", "card", "stage", "round", "slot", "chunk"}

# role -> (long form, short form); both name the same report
CASES = {
    "reviewer": (
        {"schema": "overseer.reviewer/1", "card": "WF-12", "stage": "impl-review", "round": 2,
         "slot": "B", "status": "found wanting",
         "counts": {"critical": 1, "important": 0, "minor": 3},
         "detail": f"{D}/impl-review/r2-B.md", "learned": []},
        {"status": "found wanting", "counts": {"critical": 1, "important": 0, "minor": 3},
         "detail": f"{D}/impl-review/r2-B.md", "learned": []},
    ),
    "implementer": (
        {"schema": "overseer.implementer/1", "card": "WF-12", "stage": "implementation",
         "chunk": 3, "status": "DONE", "tests": {"passed": 4, "total": 4}, "commits": ["abc"],
         "detail": f"{D}/implementation/c3.md", "learned": []},
        {"status": "DONE", "tests": {"passed": 4, "total": 4}, "commits": ["abc"],
         "detail": f"{D}/implementation/c3.md", "learned": []},
    ),
    "fixer": (
        {"schema": "overseer.fixer/1", "card": "WF-12", "stage": "plan-review", "round": 1,
         "status": "DONE", "counts": {"fixed": 2, "disputed": 0}, "commits": [],
         "detail": f"{D}/plan-review/r1-fix.md", "learned": []},
        {"status": "DONE", "counts": {"fixed": 2, "disputed": 0}, "commits": [],
         "detail": f"{D}/plan-review/r1-fix.md", "learned": []},
    ),
    "planner": (
        {"schema": "overseer.planner/1", "card": "WF-12", "stage": "planning", "status": "DONE",
         "detail": f"{D}/planning/plan.md", "learned": []},
        {"status": "DONE", "detail": f"{D}/planning/plan.md", "learned": []},
    ),
    "verifier": (
        {"schema": "overseer.verifier/1", "card": "WF-12", "stage": "verification",
         "status": "PASS", "detail": f"{D}/verification/verification.md", "learned": []},
        {"status": "PASS", "detail": f"{D}/verification/verification.md", "learned": []},
    ),
}


@pytest.mark.parametrize("role", CASES)
def test_short_form_parses_to_the_same_report_as_the_long_form(role):
    long, short = CASES[role]
    assert parse_report(role, short) == parse_report(role, long)


@pytest.mark.parametrize("role", CASES)
def test_short_form_through_the_message_parser(role):
    _, short = CASES[role]
    text = f"done\n```overseer-report\n{json.dumps(short)}\n```\n"
    assert parse_report_message(role, text).card == "WF-12"


@pytest.mark.parametrize("role", CASES)
def test_explicit_identity_fields_are_still_checked_against_the_detail_path(role):
    long, _ = CASES[role]
    with pytest.raises(ReportError, match="outside the dispatch directory"):
        parse_report(role, {**long, "card": "WF-99"})


def test_a_reviewer_detail_that_names_no_round_and_slot_is_rejected_clearly():
    _, short = CASES["reviewer"]
    with pytest.raises(ReportError) as exc:
        parse_report("reviewer", {**short, "detail": f"{D}/impl-review/notes.md"})
    assert "missing field 'round'" in exc.value.errors and "missing field 'slot'" in exc.value.errors


def test_explicit_round_is_trusted_as_before_the_filename_only_fills_gaps():
    long, _ = CASES["reviewer"]
    assert parse_report("reviewer", {**long, "round": 1}).round == 1


def test_a_short_form_with_no_detail_still_reports_the_detail_error():
    with pytest.raises(ReportError, match="detail"):
        parse_report("planner", {"status": "DONE", "learned": []})


def test_unknown_fields_are_still_refused():
    _, short = CASES["verifier"]
    with pytest.raises(ReportError, match="unknown field"):
        parse_report("verifier", {**short, "extra": 1})


@pytest.mark.parametrize("role", CASES)
def test_json_schema_makes_identity_fields_optional_but_keeps_them_known(role):
    schema = schemas.json_schema(role)
    assert not IDENTITY & set(schema["required"])
    assert {"schema", "card", "stage"} <= set(schema["properties"])


@pytest.mark.parametrize("role", CASES)
def test_agent_definitions_show_the_short_form(role):
    text = (AGENTS / f"overseer-{role}.md").read_text()
    block = re.search(r"```overseer-report\n(.+?)\n```", text, flags=re.DOTALL).group(1)
    assert not IDENTITY & set(json.loads(block)), "the example must be the short form"
    assert parse_report(role, json.loads(block)).card == "WF-12"


@pytest.mark.parametrize("role", CASES)
def test_the_bounce_message_shows_the_short_shape(role):
    shape = json.loads(EXPECTED_SHAPE[role].replace("|", "/"))
    assert not IDENTITY & set(shape)
