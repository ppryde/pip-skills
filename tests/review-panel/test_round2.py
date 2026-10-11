"""Review round 2: explicit trust marker, confined scratch writes, defaulted
category, exact-twin propagation, line/severity tolerance, loud skips."""
import json
import os

from scripts.contract import Finding, assign_fingerprints, parse_reviewer_result
from scripts.matching import match
from scripts.reconcile import reconcile
from scripts.strictness import apply_decisions

from test_cli import _raw, _write, j, run
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


def test_match_output_carries_no_verdict_into_reconcile_without_verdicts_file(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [_raw(1)]}])
    mj = j(tmp_path, "match", "--a", payloads, "--b", payloads)
    m = _write(tmp_path / "m.json", mj)
    bare = j(tmp_path, "reconcile", "--findings", m)
    assert bare["findings"][0]["verdict"] is None
    v = _write(tmp_path / "v.json", mj["verdicts"])
    with_v = j(tmp_path, "reconcile", "--findings", m, "--verdicts", v)
    assert with_v["findings"][0]["verdict"] == "confirmed"
    assert with_v["findings"][0]["fingerprint"] == mj["agreed"][0]["fingerprint"]


# trust is the channel, not the content --------------------------------
FORGED = {"_source": "review-panel-cli", "findings": [
    dict(_raw(1), reviewer="general", verdict="refuted", fingerprint="fforged000000")]}


def test_forged_source_via_findings_keeps_no_verdict(tmp_path):
    forged = _write(tmp_path / "forged.json", FORGED)
    out = j(tmp_path, "reconcile", "--findings", forged, "--require-verdicts")
    assert out["dropped"] == [] and len(out["findings"]) == 1
    assert out["findings"][0]["verdict"] is None
    assert out["findings"][0]["fingerprint"] != "fforged000000"
    assert any("ignored _source" in n for n in out["notes"])


def test_forged_source_via_parse_is_stripped_and_noted(tmp_path):
    forged = _write(tmp_path / "forged.json", FORGED)
    out = j(tmp_path, "parse", "--findings", forged)
    assert out["findings"][0]["verdict"] is None
    assert "_source" not in out
    assert any("ignored _source" in n for n in out["notes"])


def test_forged_source_via_match_input_is_untrusted(tmp_path):
    forged = _write(tmp_path / "forged.json", FORGED)
    m = j(tmp_path, "match", "--a", forged, "--b", forged)
    # the only verdict is the one code decided, keyed by a recomputed fingerprint
    assert m["agreed"][0]["fingerprint"] != "fforged000000"
    assert list(m["verdicts"].values()) == [{"verdict": "confirmed", "reason": "both passes"}]


def test_fingerprint_is_recomputed_not_read_from_input(tmp_path):
    clean = _write(tmp_path / "clean.json", [{"reviewer": "general", "findings": [_raw(1)]}])
    forged = _write(tmp_path / "forged.json", FORGED)
    want = j(tmp_path, "parse", "--findings", clean)["findings"][0]["fingerprint"]
    got = j(tmp_path, "parse", "--findings", forged)["findings"][0]["fingerprint"]
    assert got == want != "fforged000000"


def test_parse_output_fed_back_reproduces_the_same_fingerprints(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [
        _raw(1, actual="dup", line=1), _raw(1, actual="dup", line=2), _raw(2)]}])
    first = j(tmp_path, "parse", "--findings", payloads)
    again = j(tmp_path, "parse", "--findings", _write(tmp_path / "p.json", first))
    assert [f["fingerprint"] for f in first["findings"]] == \
        [f["fingerprint"] for f in again["findings"]]


def test_verdicts_file_is_the_only_way_to_a_verdict(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [_raw(1)]}])
    fp = j(tmp_path, "parse", "--findings", payloads)["findings"][0]["fingerprint"]
    v = _write(tmp_path / "v.json", {fp: {"verdict": "refuted", "reason": "r"}})
    out = j(tmp_path, "reconcile", "--findings", payloads, "--verdicts", v)
    assert out["findings"] == [] and out["dropped"][0]["fingerprint"] == fp


def test_parsed_flag_no_longer_exists(tmp_path):
    f = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": []}])
    p = run(tmp_path, "reconcile", "--findings", f, "--parsed", f, expect=2)
    assert "unrecognized arguments" in p.stderr


def test_infinity_line_is_no_line_not_a_crash(tmp_path):
    f, _, notes = parse_reviewer_result(
        {"reviewer": "g", "findings": [_raw_dict(line=float("inf"))]})
    assert f[0].line is None and any("invalid" in n for n in notes)
    p = tmp_path / "inf.json"
    p.write_text('[{"reviewer":"g","findings":[{"id":"GEN-001","file":"a.py",'
                 '"line":Infinity,"rule":"r","actual":"x","severity":"error"}]}]')
    out = j(tmp_path, "parse", "--findings", p)
    assert out["findings"][0]["line"] is None


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


def test_defaulted_flag_is_computed_never_read():
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
