"""Review round 4: type validation, list-shaped flat input, override severity
validation, corrupt decisions, malformed report input, SKILL size."""
import json

from scripts.contract import assign_fingerprints, parse_reviewer_result
from scripts.strictness import apply_decisions

from test_cli import _raw, _write, j, run


def _p(**kw):
    return {"reviewer": "general", "findings": [_raw(1, **kw)]}


def _err(p):
    return json.loads(p.stdout)


def test_wrong_typed_fields_are_rejected_not_traceback():
    for key, bad in (("file", [1]), ("file", None), ("rule", {"a": 1}), ("actual", [1]),
                     ("id", ["x"]), ("file", True)):
        f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [_raw(1, **{key: bad})]})
        assert f == [] and any(n.startswith("REJECTED") and key in n for n in notes), (key, notes)


def test_numbers_are_coerced_to_strings():
    f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [
        _raw(1, file=5, rule=1.5, actual=7, id=3)]})
    assert (f[0].file, f[0].rule, f[0].actual, f[0].id) == ("5", "1.5", "7", "3")
    assert not any(n.startswith("REJECTED") for n in notes)


def test_bad_reviewer_type_cli_gives_note_not_traceback(tmp_path):
    path = _write(tmp_path / "f.json", [{"reviewer": [1], "findings": [_raw(1)]},
                                        {"reviewer": 7, "findings": [_raw(2)]}])
    out = j(tmp_path, "parse", "--findings", path)
    assert [f["reviewer"] for f in out["findings"]] == ["7"]
    assert any(n.startswith("REJECTED") for n in out["notes"])
    flat = _write(tmp_path / "g.json", {"findings": [dict(_raw(1), reviewer=[1])]})
    out = j(tmp_path, "parse", "--findings", flat)
    assert out["findings"] == [] and any("REJECTED" in n for n in out["notes"])


def test_cli_wrong_typed_finding_field_is_a_note(tmp_path):
    path = _write(tmp_path / "f.json", [_p(file=[1])])
    out = j(tmp_path, "parse", "--findings", path)
    assert out["findings"] == [] and any("REJECTED" in n for n in out["notes"])


def test_mixed_id_types_sort_without_typeerror(tmp_path):
    f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [
        _raw(1, id=5, line=3, rule_id="GEN-001"), _raw(1, id="A-1", line=3, rule_id="GEN-001")]})
    assert len({x.fingerprint for x in assign_fingerprints(f)}) == 2


def test_flat_lists_must_be_lists(tmp_path):
    for key in ("agreed", "only_a", "only_b"):
        for bad in (5, {"a": 1}, "x"):
            path = _write(tmp_path / "f.json", {key: bad})
            out = _err(run(tmp_path, "parse", "--findings", path, expect=2))
            assert out["status"] == "error" and key in out["error"], (key, bad, out)


def test_override_severity_validated():
    f = assign_fingerprints(parse_reviewer_result({"reviewer": "g", "findings": [_raw(1)]})[0])
    for bad in ("fatal", ["x"], 5):
        notes: list[str] = []
        out = apply_decisions(f, {"overrides": {f[0].fingerprint: {"severity": bad}}}, notes)
        assert out[0].severity == "error"
        assert any("invalid" in n for n in notes), bad
    out = apply_decisions(f, {"overrides": {f[0].fingerprint: {"severity": "info"}}}, [])
    assert out[0].severity == "info"


def test_overrides_not_a_mapping_is_noted():
    notes: list[str] = []
    assert apply_decisions([], {"overrides": [1]}, notes) == []
    assert any("not a mapping" in n for n in notes)


def test_corrupt_decisions_yaml_is_clierror_with_path(tmp_path):
    findings = _write(tmp_path / "f.json", [_p()])
    dec = tmp_path / "bad.yml"
    dec.write_text("x: [\n")
    p = run(tmp_path, "reconcile", "--findings", findings, "--decisions", dec, expect=2)
    out = _err(p)
    assert out["status"] == "error" and str(dec) in out["error"]
    assert "Traceback" not in p.stderr


def test_report_rejects_malformed_reconcile_input(tmp_path):
    cases = [
        {"findings": [{"id": "x"}]},
        {"findings": [dict(_raw(1), reviewer="g", severity="fatal")]},
        {"findings": ["nope"]},
        {"findings": [], "dropped": 5},
        {"findings": [dict(_raw(1), reviewer="g", file=[1])]},
    ]
    for i, c in enumerate(cases):
        path = _write(tmp_path / f"r{i}.json", c)
        p = run(tmp_path, "report", "--reconciled", path, "--strategy", "s", "--scope", "changed",
                expect=2)
        assert _err(p)["status"] == "error" and "Traceback" not in p.stderr, c


def test_match_docstring_says_raw_payloads():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "plugins/review-panel/scripts/cli.py").read_text()
    assert "RAW reviewer" in src


# ---- round 5 ----

def test_null_suggestion_and_category_default_not_reject():
    f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [
        _raw(1, suggestion=None, category=None)]})
    assert len(f) == 1 and f[0].suggestion == "" and f[0].category == "general"
    assert not any(n.startswith("REJECTED") for n in notes)
    assert any("defaulted" in n for n in notes)


def test_null_id_still_rejected():
    f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [_raw(1, file=None)]})
    assert f == [] and any(n.startswith("REJECTED") for n in notes)


def test_non_list_findings_is_a_note_not_a_traceback(tmp_path):
    for bad in (5, True, 1.5, "x", {"a": 1}):
        f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": bad})
        assert f == [] and any("REJECTED findings" in n for n in notes), bad
        path = _write(tmp_path / "in.json", [{"reviewer": "g", "findings": bad}])
        for cmd in ("parse", "reconcile"):
            p = run(tmp_path, cmd, "--findings", path)
            assert p.returncode == 0 and "Traceback" not in p.stderr, (cmd, bad, p.stderr)


def test_non_string_payload_notes_are_coerced(tmp_path):
    path = _write(tmp_path / "in.json", [{"reviewer": "g", "findings": [_raw(1)], "notes": [1, None, {"a": 1}]}])
    p = run(tmp_path, "reconcile", "--findings", path)
    assert p.returncode == 0 and "Traceback" not in p.stderr
    assert all(isinstance(n, str) for n in json.loads(p.stdout)["notes"])


def test_report_top_level_notes_not_a_list(tmp_path):
    for bad in (5, True, 1.5, "x"):
        rec = _write(tmp_path / "rec.json", {"findings": [], "dropped": [], "notes": bad})
        p = run(tmp_path, "report", "--reconciled", rec, "--strategy", "s", "--scope", "x")
        assert p.returncode == 0 and "Traceback" not in p.stderr, (bad, p.stderr)


def test_every_bad_override_severity_emits_a_note():
    f = assign_fingerprints(parse_reviewer_result({"reviewer": "g", "findings": [_raw(1)]})[0])
    for bad in ("fatal", ["x"], {"a": 1}, None, True, 5, "Error"):
        notes: list[str] = []
        out = apply_decisions(f, {"overrides": {f[0].fingerprint: {"severity": bad}}}, notes)
        assert out[0].severity == "error"
        assert any("invalid" in n for n in notes), bad
