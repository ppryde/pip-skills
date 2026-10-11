"""Fingerprint-keyed decisions with the legacy id fallback (RP-3)."""
from dataclasses import replace

from scripts.contract import Finding
from scripts.strictness import apply_decisions, load_decisions


def _f(id_="G1", fingerprint="fabc123def456", severity="error"):
    return Finding(reviewer="general", id=id_, file="a.py", rule="r", actual="x",
                   severity=severity, category="c", suggestion="s",
                   fingerprint=fingerprint)


def test_override_by_fingerprint_without_note():
    notes = []
    out = apply_decisions([_f()], {"overrides": {
        "fabc123def456": {"severity": "info", "reason": "ok"}}}, notes)
    assert out[0].severity == "info" and out[0].reason == "ok"
    assert notes == []


def test_legacy_id_key_still_matches_with_migrate_note():
    notes = []
    out = apply_decisions([_f()], {"overrides": {"G1": {"severity": "info"}}}, notes)
    assert out[0].severity == "info"
    assert notes == ["legacy id-keyed override matched: G1; migrate"]


def test_notes_argument_is_optional():
    out = apply_decisions([_f()], {"overrides": {"G1": {"severity": "info"}}})
    assert out[0].severity == "info"


def test_fingerprint_key_present_blocks_id_fallback():
    notes = []
    mine = replace(_f(), fingerprint="fmine00000000")
    out = apply_decisions([mine], {"overrides": {
        "fmine00000000": {"severity": "warning"},
        "G1": {"severity": "info"}}}, notes)
    assert out[0].severity == "warning" and notes == []


def test_unmatched_fingerprint_does_not_hit_other_findings():
    out = apply_decisions([_f(id_="G2", fingerprint="fother0000000")],
                          {"overrides": {"fabc123def456": {"severity": "info"}}})
    assert out[0].severity == "error"


def test_integer_like_yaml_keys_match_as_strings(tmp_path):
    p = tmp_path / "d.yml"
    p.write_text("overrides:\n  123456: { severity: info }\n")
    out = apply_decisions([_f(id_="123456", fingerprint=None)], load_decisions(p))
    assert out[0].severity == "info"


def test_non_mapping_override_is_ignored():
    out = apply_decisions([_f()], {"overrides": {"fabc123def456": "info"}})
    assert out[0].severity == "error"
