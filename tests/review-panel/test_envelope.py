"""review-panel ADOPTS the pip-agents envelope: a seat's final message is validated by the vendored validator and
adapted to the finding payload the rest of the pipeline already reads (MAPPING.md sections 1.1 and 1.2)."""
import json
from pathlib import Path

import pytest

from scripts.contract import apply_verdicts, assign_fingerprints, parse_reviewer_result, render_report, collate
from scripts.envelope import Ingested, ingest, reviewer_payload, verdict_map

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "plugins" / "pip-agents" / "contract" / "examples"


def example(name):
    return (EXAMPLES / name).read_text()


def block(env: dict) -> str:
    return "Done.\n\n```pip-agents-result\n" + json.dumps(env) + "\n```\n"


def review_env(**over):
    env = json.loads(example("review.result.md").split("```pip-agents-result\n")[1].split("\n```")[0])
    env.update(over)
    return env


def test_example_review_is_adapted():
    got = ingest(example("review.result.md"), example("review.brief.txt"), "reviewer-scope")
    assert isinstance(got, Ingested) and got.ok, got.errors
    assert got.kind == "review"
    p = got.payload
    assert p["reviewer"] == "seat-2"
    (f,) = p["findings"]
    assert f["id"] == "scope-1" and f["file"] == "plugins/census/scripts/store.py" and f["line"] == 148
    assert f["severity"] == "warning"  # important -> warning
    assert f["rule"].startswith("pending queue now drops")  # no `rule`, so the claim
    assert f["actual"].startswith("store.py:148")  # evidence
    assert f["suggestion"] == "remove the expiry or add it to the intent"
    assert "README.md" in p["clean_files"] and "plugins/census/scripts/store.py" not in p["clean_files"]
    assert "unchecked: store.py L1-80: outside the function-context hunks" in p["notes"]
    assert any(n.startswith("out of lens: ") for n in p["notes"])


def test_adapted_payload_goes_through_the_existing_parser():
    got = ingest(example("review.result.md"), example("review.brief.txt"), "reviewer-scope")
    findings, clean, notes = parse_reviewer_result(got.payload, strict=True)
    assert findings[0].reviewer == "seat-2" and findings[0].severity == "warning"
    assert "README.md" in clean


@pytest.mark.parametrize("sev,want", [("critical", "error"), ("important", "warning"), ("minor", "info")])
def test_severity_words_translate(sev, want):
    env = review_env()
    env["payload"]["findings"][0]["severity"] = sev
    got = ingest(block(env), example("review.brief.txt"), "reviewer-scope")
    assert got.ok and got.payload["findings"][0]["severity"] == want


def test_line_zero_means_whole_file():
    env = review_env()
    env["payload"]["findings"][0]["line"] = 0
    got = ingest(block(env), example("review.brief.txt"), "reviewer-scope")
    assert "line" not in got.payload["findings"][0]
    findings, _, notes = parse_reviewer_result(got.payload)
    assert findings[0].line is None and not any("line" in n for n in notes)


def test_medium_findings_are_kept_and_tagged():
    env = review_env()
    med = dict(env["payload"]["findings"][0], id="scope-2", line=9)
    env["payload"]["medium"] = [med]
    got = ingest(block(env), example("review.brief.txt"), "reviewer-scope")
    assert [f["id"] for f in got.payload["findings"]] == ["scope-1", "scope-2"]
    assert got.payload["findings"][1]["tier"] == "medium"
    findings, _, _ = parse_reviewer_result(got.payload)
    assert findings[0].tier is None and findings[1].tier == "medium"
    report = render_report(collate(assign_fingerprints(findings)), {})
    assert "(medium)" in report


def test_tier_is_inert_except_medium():
    payload = {"reviewer": "r", "findings": [{
        "id": "G-001", "file": "a", "rule": "x", "actual": "y", "severity": "error", "tier": "confirmed"}]}
    (f,), _, _ = parse_reviewer_result(payload)
    assert f.tier is None and f.verdict is None


def test_rules_lens_keeps_rule_and_citation_and_reports_rules_checked():
    brief = ("brief: pip-agents/1\nkind: review\nref: general\ntarget: /t/diff.patch\n"
             "rules: /r/general.md L10-21 (GEN-001,GEN-002)\n")
    env = {"result": "pip-agents/1", "kind": "review", "persona": "reviewer-rules", "ref": "general",
           "status": "ok", "summary": "s", "checked": ["a.py"], "unchecked": [], "out_of_lens": [],
           "injection_attempts": ["a.py:3 \"ignore previous\""],
           "payload": {"lens": "rules", "findings": [{
               "id": "GEN-001", "rule": "Logic error or wrong result on a changed path", "file": "a.py",
               "line": 4, "severity": "critical", "category": "correctness", "claim": "c",
               "evidence": "a.py:4 inverted", "fix": "flip it", "citation": "https://example.com/c/1"}],
               "medium": [], "rules_checked": "2/2", "n_a": []}}
    got = ingest(block(env), brief, "reviewer-rules")
    assert got.ok, got.errors
    f = got.payload["findings"][0]
    assert f["rule"] == "Logic error or wrong result on a changed path" and f["citation"] == "https://example.com/c/1"
    assert "rules checked: 2/2" in got.payload["notes"]
    assert any(n.startswith("injection: ") for n in got.payload["notes"])
    assert got.injection_attempts == ["a.py:3 \"ignore previous\""]
    (pf,), _, _ = parse_reviewer_result(got.payload)
    assert pf.rule_id == "GEN-001"


def test_validator_example_gives_a_verdict_map(tmp_path):
    claims = tmp_path / "claims-1.json"
    claims.write_text(json.dumps([{"id": "f3a1", "claim": "x", "where": "a:1"}, {"id": "9bc0", "claim": "y", "where": "a:2"}]))
    brief = example("validate.brief.txt").replace("/tmp/pip-agents/r81/claims-1.json", str(claims))
    got = ingest(example("validate.result.md"), brief, "validator")
    assert got.ok, got.errors
    assert got.kind == "validate"
    assert set(got.verdicts) == {"f3a1", "9bc0"}
    assert got.verdicts["f3a1"]["verdict"] == "weakened"
    assert "pending entries with no session key" in got.verdicts["f3a1"]["reason"]  # restated is kept
    assert got.verdicts["9bc0"] == {"verdict": "refuted", "reason": got.verdicts["9bc0"]["reason"]}
    assert got.verdicts["9bc0"]["reason"].startswith("unverified:")
    assert got.injection_attempts


def test_verdict_map_feeds_apply_verdicts():
    payload = {"reviewer": "r", "findings": [
        {"id": "X-001", "file": "a", "rule": "x", "actual": "y", "severity": "error"}]}
    (f,), _, _ = parse_reviewer_result(payload)
    (f,) = assign_fingerprints([f])
    from dataclasses import replace
    r = apply_verdicts([replace(f, verdict="weakened")])
    assert r.kept[0].severity == "warning"


def test_status_error_is_a_seat_error_not_a_rejection():
    brief = "brief: pip-agents/1\nkind: review\nref: seat-1\ntarget: /t/d.patch\n"
    env = {"result": "pip-agents/1", "kind": "review", "persona": "reviewer-scope", "ref": "seat-1",
           "status": "error", "error": "target: unreadable", "summary": "not started", "checked": [],
           "unchecked": [], "out_of_lens": [], "injection_attempts": []}
    got = ingest(block(env), brief, "reviewer-scope")
    assert got.ok and got.seat_error == "target: unreadable"
    assert got.payload == {"reviewer": "seat-1", "findings": [], "clean_files": [],
                           "notes": ["seat error: target: unreadable"]}


def test_partial_keeps_findings_and_notes_the_unchecked():
    env = review_env(status="partial")
    got = ingest(block(env), example("review.brief.txt"), "reviewer-scope")
    assert got.ok and len(got.payload["findings"]) == 1
    assert any(n.startswith("unchecked: ") for n in got.payload["notes"])


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e.update(ref="seat-9"), "ref"),
    (lambda e: e.update(persona="reviewer-rules"), "persona"),
    (lambda e: e["payload"].update(lens="rules"), "lens"),
    (lambda e: e["payload"]["findings"][0].update(confidence="high"), "confidence"),
    (lambda e: e["payload"]["findings"][0].update(file="other.py"), "other.py"),
])
def test_invalid_results_are_rejected_whole(mutate, needle):
    env = review_env()
    mutate(env)
    got = ingest(block(env), example("review.brief.txt"), "reviewer-scope")
    assert not got.ok and got.payload is None
    assert any(needle in e for e in got.errors), got.errors


def test_no_block_and_json_fence_are_rejected():
    assert not ingest("all clean", example("review.brief.txt"), "reviewer-scope").ok
    fenced = "```json\n" + json.dumps(review_env()) + "\n```"
    got = ingest(fenced, example("review.brief.txt"), "reviewer-scope")
    assert not got.ok and any("E_NO_BLOCK" in e for e in got.errors)


def test_bad_brief_is_an_error_not_a_crash():
    got = ingest(example("review.result.md"), "not a brief line\n", "reviewer-scope")
    assert not got.ok and got.errors


def test_review_brief_needs_a_ref():
    got = ingest(example("review.result.md"), "brief: pip-agents/1\nkind: review\ntarget: /t/d.patch\n", "reviewer-scope")
    assert not got.ok and any("ref" in e for e in got.errors)


def test_helpers_are_pure():
    env = review_env()
    before = json.dumps(env, sort_keys=True)
    reviewer_payload(env, "seat-2")
    assert json.dumps(env, sort_keys=True) == before
    assert verdict_map({"payload": {"verdicts": []}}) == {}
