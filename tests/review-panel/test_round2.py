"""Review round 2: explicit trust marker, confined scratch writes, defaulted
category, exact-twin propagation, line/severity tolerance, loud skips."""
import json
import os

from scripts.contract import Finding, assign_fingerprints, parse_reviewer_result
from scripts.matching import match
from scripts.reconcile import reconcile
from scripts.strictness import apply_decisions

from test_cli import _raw, _write, j
from test_round1 import _raw_dict


def _mk(line, actual="same", **kw):
    base = dict(reviewer="general", id="GEN-001", file="a.py", rule="r", actual=actual,
                severity="error", category="c", suggestion="s", line=line,
                rule_id="GEN-001")
    base.update(kw)
    return Finding(**base)


# trust is a marker, not a shape ---------------------------------------
def test_planted_verdict_in_no_reviewer_flat_file_is_ignored(tmp_path):
    planted = _write(tmp_path / "p.json", {"findings": [
        dict(_raw(1), reviewer="general", verdict="refuted", reason="planted",
             fingerprint="fforged000000")]})
    out = j(tmp_path, "reconcile", "--findings", planted, "--require-verdicts")
    assert len(out["findings"]) == 1 and out["dropped"] == []
    assert out["findings"][0]["verdict"] is None
    assert out["findings"][0]["fingerprint"] != "fforged000000"
    assert out["counts"]["unverified"] == 1


def test_planted_verdict_in_bare_payload_is_ignored(tmp_path):
    bare = _write(tmp_path / "b.json", {"findings": [
        dict(_raw(1), verdict="refuted")]})  # no top-level reviewer at all
    out = j(tmp_path, "reconcile", "--findings", bare)
    assert out["findings"] == [] and out["dropped"] == []
    assert "REJECTED GEN-001: missing reviewer" in out["notes"]


def test_parse_and_match_output_carry_the_marker_and_are_trusted(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [_raw(1)]}])
    parsed = j(tmp_path, "parse", "--findings", payloads)
    assert parsed["_source"] == "review-panel-cli"
    m = j(tmp_path, "match", "--a", payloads, "--b", payloads)
    assert m["_source"] == "review-panel-cli"
    out = j(tmp_path, "reconcile", "--findings", _write(tmp_path / "m.json", m))
    assert out["findings"][0]["verdict"] == "confirmed"


def test_removing_the_marker_strips_trust(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [_raw(1)]}])
    m = j(tmp_path, "match", "--a", payloads, "--b", payloads)
    del m["_source"]
    out = j(tmp_path, "reconcile", "--findings", _write(tmp_path / "m.json", m))
    assert out["findings"][0]["verdict"] is None


# reconcile --out confinement ------------------------------------------
def test_reconcile_out_into_temp_dir_is_allowed(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": []}])
    rec = tmp_path / "rec.json"
    j(tmp_path, "reconcile", "--findings", payloads, "--out", rec)
    assert json.loads(rec.read_text())["status"] == "ok"


def test_reconcile_out_outside_cwd_and_tmp_is_refused(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": []}])
    out = j(tmp_path, "reconcile", "--findings", payloads, "--out",
            os.path.expanduser("~/review-panel-should-not-exist.json"), expect=2)
    assert out["status"] == "error" and "outside" in out["error"]


def test_reconcile_out_symlink_is_refused(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("keep")
    os.symlink(victim, work / "link.json")
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": []}])
    j(tmp_path, "reconcile", "--findings", payloads, "--out", "link.json", expect=2)
    assert victim.read_text() == "keep"


# defaulted category ---------------------------------------------------
def test_defaulted_category_is_flagged_and_noted_with_location():
    raw = _raw_dict(line=7)
    del raw["category"]
    f, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [raw]})
    assert f[0].category_defaulted is True
    assert any("category missing" in n and "a.py:7" in n for n in notes)


def test_never_pair_on_a_defaulted_category():
    a = _mk(10, id="x", rule_id=None, category="general", category_defaulted=True)
    b = _mk(10, id="y", rule_id=None, category="general")
    assert not match([a], [b]).agreed
    c = _mk(10, id="z", rule_id=None, category="general")
    assert len(match([b], [c]).agreed) == 1


def test_defaulted_flag_survives_trusted_roundtrip():
    f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [
        dict(_raw_dict(), category_defaulted=True)]}, trusted=True)
    assert f[0].category_defaulted is True
    g, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [
        dict(_raw_dict(), category_defaulted=True)]})
    assert g[0].category_defaulted is False


# twin needs the same actual -------------------------------------------
def test_twin_with_different_actual_does_not_inherit_refuted():
    fs = assign_fingerprints([_mk(10, actual="a"), _mk(11, actual="b")])
    res = reconcile(fs, verdicts={fs[0].fingerprint: {"verdict": "refuted"}})
    assert [f.actual for f in res.findings] == ["b"]
    assert not any(n.startswith("verdict propagated") for n in res.notes)


def test_twin_actual_compared_normalised():
    fs = assign_fingerprints([_mk(10, actual="Foo  bar"), _mk(11, actual="foo bar")])
    res = reconcile(fs, verdicts={fs[0].fingerprint: {"verdict": "refuted"}})
    assert res.findings == [] and len(res.dropped) == 2


# tolerance ------------------------------------------------------------
def test_suggestion_severity_maps_to_info():
    f, _, _ = parse_reviewer_result(
        {"reviewer": "g", "findings": [_raw_dict(severity="suggestion")]})
    assert f[0].severity == "info"


def test_line_below_one_is_rejected_to_none_with_note():
    for bad in (0, -3, "0"):
        f, _, notes = parse_reviewer_result(
            {"reviewer": "g", "findings": [_raw_dict(line=bad)]})
        assert f[0].line is None and any("invalid" in n for n in notes), bad
    ok, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [_raw_dict(line=1)]})
    assert ok[0].line == 1


# loud skips -----------------------------------------------------------
def test_non_mapping_override_is_noted():
    notes = []
    f = assign_fingerprints([_mk(1)])
    out = apply_decisions(f, {"overrides": {f[0].fingerprint: "info"}}, notes)
    assert out[0].severity == "error"
    assert notes == [f"override ignored (not a mapping): {f[0].fingerprint}"]
