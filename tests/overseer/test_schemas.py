from pathlib import Path

import pytest

from scripts import schemas
from scripts.schemas import (
    FixerReport,
    ImplementerReport,
    LearnedFact,
    PlannerReport,
    ReportError,
    ReviewerReport,
    VerifierReport,
    extract_report_block,
    json_schema,
    parse_report,
    parse_report_message,
    schema_text,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "schemas"

D = "/x/state/dispatch/WF-12/impl-review"
DI = "/x/state/dispatch/WF-12/implementation"
DP = "/x/state/dispatch/WF-1/planning"
DV = "/x/state/dispatch/WF-1/verification"


def _learned():
    return [{"statement": "x is y", "tags": ["a", "b"]}]


class TestReviewer:
    def valid(self, **over):
        obj = {
            "schema": "overseer.reviewer/1", "card": "WF-12", "stage": "impl-review",
            "round": 1, "slot": "A", "status": "found wanting",
            "counts": {"critical": 1, "important": 2, "minor": 0},
            "detail": f"{D}/r1-A.md", "learned": _learned(),
        }
        obj.update(over)
        return obj

    def test_valid(self):
        r = parse_report("reviewer", self.valid())
        assert isinstance(r, ReviewerReport)
        assert (r.status, r.round, r.slot) == ("found wanting", 1, "A")
        assert (r.critical, r.important, r.minor) == (1, 2, 0)
        assert r.detail == Path(f"{D}/r1-A.md")
        assert r.learned == (LearnedFact("x is y", ("a", "b")),)

    def test_missing_field(self):
        obj = self.valid()
        del obj["round"]
        with pytest.raises(ReportError, match="missing field 'round'"):
            parse_report("reviewer", obj)

    def test_unknown_field(self):
        with pytest.raises(ReportError, match="unknown field"):
            parse_report("reviewer", self.valid(extra="nope"))

    def test_wrong_type(self):
        with pytest.raises(ReportError, match="non-negative integer"):
            parse_report("reviewer", self.valid(round="one"))

    def test_bad_enum(self):
        with pytest.raises(ReportError, match="one of"):
            parse_report("reviewer", self.valid(status="LGTM"))

    def test_bad_schema_version(self):
        with pytest.raises(ReportError, match="schema"):
            parse_report("reviewer", self.valid(schema="overseer.reviewer/2"))

    def test_path_outside_dispatch_dir(self):
        with pytest.raises(ReportError, match="outside the dispatch directory"):
            parse_report("reviewer", self.valid(detail="/tmp/elsewhere/r1-A.md"))

    def test_path_card_mismatch(self):
        with pytest.raises(ReportError, match="outside the dispatch directory"):
            parse_report(
                "reviewer",
                self.valid(detail="/x/state/dispatch/WF-99/impl-review/r1-A.md"),
            )

    def test_counts_unknown_field(self):
        obj = self.valid()
        obj["counts"] = {"critical": 1, "important": 0, "minor": 0, "extra": 1}
        with pytest.raises(ReportError, match="counts has unknown"):
            parse_report("reviewer", obj)

    def test_multiple_errors_all_reported(self):
        with pytest.raises(ReportError) as exc:
            parse_report("reviewer", self.valid(status="LGTM", extra="nope"))
        assert len(exc.value.errors) >= 2

    def test_not_an_object(self):
        with pytest.raises(ReportError, match="must be a JSON object"):
            parse_report("reviewer", "approved")

    def test_learned_unknown_field(self):
        obj = self.valid(learned=[{"statement": "x", "tags": [], "extra": 1}])
        with pytest.raises(ReportError, match="learned\\[0\\] has unknown"):
            parse_report("reviewer", obj)

    def test_learned_none_is_empty_list(self):
        r = parse_report("reviewer", self.valid(learned=[]))
        assert r.learned == ()


class TestImplementer:
    def valid(self, **over):
        obj = {
            "schema": "overseer.implementer/1", "card": "WF-12", "stage": "implementation",
            "chunk": 2, "status": "DONE", "tests": {"passed": 41, "total": 41},
            "commits": ["abc1234"], "detail": f"{DI}/c2.md", "learned": [],
        }
        obj.update(over)
        return obj

    def test_valid(self):
        r = parse_report("implementer", self.valid())
        assert isinstance(r, ImplementerReport)
        assert (r.chunk, r.tests_passed, r.tests_total) == (2, 41, 41)
        assert r.commits == ("abc1234",)

    def test_tests_wrong_shape(self):
        with pytest.raises(ReportError, match="'tests' must be an object"):
            parse_report("implementer", self.valid(tests=[41, 41]))

    def test_commits_must_be_strings(self):
        with pytest.raises(ReportError, match="commits"):
            parse_report("implementer", self.valid(commits=[123]))

    def test_empty_commits_is_valid(self):
        r = parse_report("implementer", self.valid(commits=[]))
        assert r.commits == ()


class TestFixer:
    def valid(self, **over):
        obj = {
            "schema": "overseer.fixer/1", "card": "WF-12", "stage": "impl-review",
            "round": 1, "status": "DISPUTED", "counts": {"fixed": 2, "disputed": 1},
            "commits": ["abc1234"], "detail": f"{D}/r1-fix.md", "learned": [],
        }
        obj.update(over)
        return obj

    def test_valid(self):
        r = parse_report("fixer", self.valid())
        assert isinstance(r, FixerReport)
        assert (r.fixed, r.disputed) == (2, 1)


class TestPlanner:
    def valid(self, **over):
        obj = {
            "schema": "overseer.planner/1", "card": "WF-1", "stage": "planning",
            "status": "DONE", "detail": f"{DP}/plan.md", "learned": [],
        }
        obj.update(over)
        return obj

    def test_valid(self):
        r = parse_report("planner", self.valid())
        assert isinstance(r, PlannerReport)
        assert r.status == "DONE"

    def test_needs_context(self):
        r = parse_report("planner", self.valid(status="NEEDS_CONTEXT"))
        assert r.status == "NEEDS_CONTEXT"


class TestVerifier:
    def valid(self, **over):
        obj = {
            "schema": "overseer.verifier/1", "card": "WF-1", "stage": "verification",
            "status": "PASS", "detail": f"{DV}/verification.md", "learned": [],
        }
        obj.update(over)
        return obj

    def test_valid(self):
        r = parse_report("verifier", self.valid())
        assert isinstance(r, VerifierReport)
        assert r.status == "PASS"


def test_no_schema_for_unknown_role():
    with pytest.raises(ReportError, match="no report schema"):
        parse_report("foreman", {})


class TestExtractBlock:
    def test_single_block(self):
        text = 'preamble\n```overseer-report\n{"a": 1}\n```\n'
        assert extract_report_block(text) == '{"a": 1}\n'

    def test_last_block_wins(self):
        text = (
            '```overseer-report\n{"a": 1}\n```\n'
            'some narration\n'
            '```overseer-report\n{"a": 2}\n```\n'
        )
        assert extract_report_block(text) == '{"a": 2}\n'

    def test_no_block_returns_none(self):
        assert extract_report_block("just some text, no fences") is None

    def test_unrelated_fence_ignored(self):
        text = '```json\n{"a": 1}\n```\n'
        assert extract_report_block(text) is None


class TestParseReportMessage:
    def test_happy_path(self):
        obj = TestVerifier().valid()
        import json as _json
        text = f"result:\n```overseer-report\n{_json.dumps(obj)}\n```\n"
        r = parse_report_message("verifier", text)
        assert r.status == "PASS"

    def test_missing_block(self):
        with pytest.raises(ReportError, match="no ```overseer-report``` block"):
            parse_report_message("verifier", "I verified everything, it's fine.")

    def test_invalid_json(self):
        text = "```overseer-report\n{not json}\n```\n"
        with pytest.raises(ReportError, match="not valid JSON"):
            parse_report_message("verifier", text)


class TestJsonSchemaDrift:
    @pytest.mark.parametrize("role", schemas.ROLES)
    def test_committed_schema_matches_generator(self, role):
        committed = (SCHEMA_DIR / f"{role}.json").read_text()
        assert committed == schema_text(role), (
            f"schemas/{role}.json is stale — run "
            "`python3 -m scripts.schemas` from plugins/overseer to regenerate"
        )

    @pytest.mark.parametrize("role", schemas.ROLES)
    def test_schema_is_well_formed(self, role):
        schema = json_schema(role)
        assert schema["additionalProperties"] is False
        assert "detail" in schema["properties"]
        assert set(schema["required"]) <= set(schema["properties"])
