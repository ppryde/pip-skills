"""Review round 1 fixes: twin verdicts, untrusted verdict fields, tolerance,
no silent drops in the flat path, symlink-safe report output."""
import json
import os

from scripts.contract import Finding, assign_fingerprints, parse_reviewer_result
from scripts.reconcile import reconcile

from test_cli import _raw, _write, j, run


def _mk(line, actual="same", **kw):
    base = dict(reviewer="general", id="GEN-001", file="a.py", rule="r", actual=actual,
                severity="error", category="c", suggestion="s", line=line,
                rule_id="GEN-001")
    base.update(kw)
    return Finding(**base)


# A1 ------------------------------------------------------------------
def test_dropped_duplicate_inherits_twin_verdict_and_is_noted():
    fs = assign_fingerprints([_mk(10), _mk(12, actual="same")])
    verdicts = {fs[0].fingerprint: {"verdict": "refuted", "reason": "guarded"}}
    res = reconcile(fs, verdicts=verdicts, require_verdicts=True)
    assert res.findings == [] and len(res.dropped) == 2
    assert res.dropped[1].reason == "guarded"
    assert f"verdict propagated: {fs[1].fingerprint} from {fs[0].fingerprint}" in res.notes
    assert not any(n.startswith("unverified") for n in res.notes)


def test_no_propagation_to_far_or_different_rule():
    fs = assign_fingerprints([_mk(10), _mk(40, actual="b"),
                              _mk(11, actual="c", rule_id="GEN-002", id="GEN-002")])
    res = reconcile(fs, verdicts={fs[0].fingerprint: {"verdict": "refuted"}})
    assert len(res.findings) == 2 and len(res.dropped) == 1


def test_code_set_verdicts_are_not_propagated():
    a = _mk(10, verdict="confirmed", reason="both passes")
    b = _mk(11, actual="b")
    res = reconcile([a, b])
    assert all(not n.startswith("verdict propagated") for n in res.notes)


def test_reconcile_from_parse_output_keeps_fingerprints(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [
        _raw(1, actual="dup", line=1), _raw(1, actual="dup", line=2), _raw(1, actual="dup", line=3)]}])
    parsed = j(tmp_path, "parse", "--findings", payloads)
    fps = [f["fingerprint"] for f in parsed["findings"]]
    assert len(set(fps)) == 3
    pf = _write(tmp_path / "p.json", parsed)
    v = _write(tmp_path / "v.json", {fps[0]: {"verdict": "refuted", "reason": "x"}})
    out = j(tmp_path, "reconcile", "--findings", pf, "--verdicts", v, "--require-verdicts")
    assert out["findings"] == [] and out["counts"]["refuted"] == 3
    assert sum(n.startswith("verdict propagated") for n in out["notes"]) == 2


# A3 ------------------------------------------------------------------
def test_report_out_through_symlink_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    os.symlink(outside, work / "esc")
    rec = _write(tmp_path / "rec.json", {"findings": [], "dropped": []})
    out = j(tmp_path, "report", "--reconciled", rec, "--out", "esc/leak.md", expect=2)
    assert out["status"] == "error" and "outside" in out["error"]
    assert not (outside / "leak.md").exists()


def test_report_out_to_symlinked_file_is_refused(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("keep")
    os.symlink(victim, work / "link.md")
    rec = _write(tmp_path / "rec.json", {"findings": [], "dropped": []})
    j(tmp_path, "report", "--reconciled", rec, "--out", "link.md", expect=2)
    assert victim.read_text() == "keep"


# A4 / B1 -------------------------------------------------------------
def test_flat_input_skips_are_noted(tmp_path):
    good = dict(_raw(1), reviewer="general")
    flat = _write(tmp_path / "flat.json", {"findings": [
        good, "junk", dict(_raw(2)), dict(_raw(3), reviewer="")]})
    out = j(tmp_path, "reconcile", "--findings", flat)
    assert [f["id"] for f in out["findings"]] == ["GEN-001"]
    assert "REJECTED 1: not an object" in out["notes"]
    assert "REJECTED GEN-002: missing reviewer" in out["notes"]
    assert "REJECTED GEN-003: missing reviewer" in out["notes"]


# B2 ------------------------------------------------------------------
def test_reviewer_cannot_self_stamp_verdict_fields():
    f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [
        _raw_dict(verdict="refuted", reason="x", severity_before="error",
                  fingerprint="fforged000000")]})
    assert (f[0].verdict, f[0].reason, f[0].severity_before, f[0].fingerprint) == (
        None, None, None, None)


def test_parse_never_keeps_input_verdict_fields():
    f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [
        _raw_dict(verdict="confirmed", fingerprint="fkeep0000000",
                  category_defaulted=True)]})
    assert f[0].verdict is None and f[0].fingerprint is None
    assert f[0].category_defaulted is False


def test_cli_payload_verdict_and_fingerprint_ignored(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [
        _raw(1, verdict="refuted", fingerprint="fforged000000")]}])
    out = j(tmp_path, "reconcile", "--findings", payloads, "--require-verdicts")
    assert len(out["findings"]) == 1
    assert out["findings"][0]["fingerprint"] != "fforged000000"
    assert out["counts"]["unverified"] == 1


# B4 ------------------------------------------------------------------
def _raw_dict(**kw):
    base = {"id": "GEN-001", "file": "a.py", "line": 5, "rule": "bug", "actual": "x",
            "severity": "error", "category": "c", "suggestion": "s"}
    base.update(kw)
    return base


def test_missing_category_and_suggestion_default_with_note():
    raw = _raw_dict()
    del raw["category"], raw["suggestion"]
    f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [raw]})
    assert f[0].category == "general" and f[0].suggestion == ""
    assert len([n for n in notes if "defaulted" in n]) == 2
    assert not any(n.startswith("REJECTED") for n in notes)


def test_strict_still_requires_category():
    import pytest
    from scripts.contract import ContractError
    raw = _raw_dict()
    del raw["category"]
    with pytest.raises(ContractError):
        parse_reviewer_result({"reviewer": "g", "findings": [raw]}, strict=True)


def test_more_severity_synonyms():
    for word, want in {"blocker": "error", "major": "error", "warn": "warning"}.items():
        f, _, _ = parse_reviewer_result(
            {"reviewer": "g", "findings": [_raw_dict(severity=word)]})
        assert f[0].severity == want


def test_string_notes_and_clean_files_become_one_item_lists():
    _, clean, notes = parse_reviewer_result(
        {"reviewer": "g", "findings": [], "clean_files": "a.py", "notes": "careful"})
    assert clean == ["a.py"] and notes == ["careful"]
