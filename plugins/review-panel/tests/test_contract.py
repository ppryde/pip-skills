import pytest

from scripts.contract import (
    Finding, ContractError, parse_reviewer_result, collate, render_report,
)

PAYLOAD = {
    "reviewer": "general",
    "files_scanned": 2,
    "findings": [
        {"id": "GEN-001", "file": "a.py", "line": 5, "rule": "bug",
         "actual": "x=1", "severity": "error", "category": "correctness",
         "suggestion": "fix"},
        {"id": "GEN-002", "file": "b.py", "line": None, "rule": "nit",
         "actual": "y", "severity": "info", "category": "style",
         "suggestion": "tidy"},
    ],
    "clean_files": ["c.py"],
    "notes": ["skipped d.py"],
}


def test_parse_valid_payload():
    findings, clean, notes = parse_reviewer_result(PAYLOAD)
    assert [f.id for f in findings] == ["GEN-001", "GEN-002"]
    assert findings[0].reviewer == "general"
    assert clean == ["c.py"] and notes == ["skipped d.py"]


def test_parse_rejects_bad_severity():
    bad = {"reviewer": "general", "findings": [
        {"id": "X", "file": "a", "rule": "r", "actual": "a",
         "severity": "nuclear", "category": "c", "suggestion": "s"}]}
    with pytest.raises(ContractError, match="severity"):
        parse_reviewer_result(bad)


def test_parse_rejects_missing_field():
    bad = {"reviewer": "general", "findings": [{"id": "X"}]}
    with pytest.raises(ContractError, match="missing"):
        parse_reviewer_result(bad)


def test_collate_groups_by_reviewer_then_severity():
    findings, _, _ = parse_reviewer_result(PAYLOAD)
    grouped = collate(findings)
    assert grouped["general"]["error"][0].id == "GEN-001"
    assert grouped["general"]["info"][0].id == "GEN-002"


def test_render_report_includes_counts_and_ids():
    findings, _, _ = parse_reviewer_result(PAYLOAD)
    out = render_report(collate(findings), {"strategy": "committee", "scope": "changed"})
    assert "committee" in out
    assert "GEN-001" in out and "GEN-002" in out
    assert "1 error" in out and "1 info" in out
