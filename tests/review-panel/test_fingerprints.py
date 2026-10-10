"""Tolerant parse (RP-13), rule_id, fingerprints and the refuted report section."""
from dataclasses import replace

import pytest

from scripts.contract import (
    ContractError, Finding, RULE_ID_RE, assign_fingerprints, collate,
    finding_from_dict, finding_to_dict, parse_reviewer_result, render_report,
)


def _raw(**kw):
    base = {"id": "GEN-001", "file": "a.py", "line": 5, "rule": "bug",
            "actual": "x=1", "severity": "error", "category": "correctness",
            "suggestion": "fix"}
    base.update(kw)
    return base


def test_tolerant_parse_keeps_valid_and_notes_rejected():
    payload = {"reviewer": "general", "findings": [
        _raw(), {"id": "BAD"}, "junk", _raw(id="GEN-002", severity="nuclear")]}
    findings, _, notes = parse_reviewer_result(payload)
    assert [f.id for f in findings] == ["GEN-001"]
    rejected = [n for n in notes if n.startswith("REJECTED")]
    assert len(rejected) == 3
    assert any(n.startswith("REJECTED BAD:") for n in rejected)
    assert any(n.startswith("REJECTED 2:") for n in rejected)
    assert any(n.startswith("REJECTED GEN-002:") for n in rejected)


def test_tolerant_parse_maps_severity_synonyms():
    mapping = {"critical": "error", "high": "error", "medium": "warning",
               "moderate": "warning", "low": "info", "minor": "info",
               "nit": "info", "ERROR": "error"}
    for word, want in mapping.items():
        f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [_raw(severity=word)]})
        assert f[0].severity == want, word


def test_tolerant_parse_coerces_line():
    ok, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [_raw(line="42")]})
    assert ok[0].line == 42
    bad, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [_raw(line="abc")]})
    assert bad[0].line is None and any("not numeric" in n for n in notes)
    none, _, notes = parse_reviewer_result({"reviewer": "g", "findings": [_raw(line=None)]})
    assert none[0].line is None and not notes


def test_strict_parse_has_no_synonyms_or_coercion():
    with pytest.raises(ContractError):
        parse_reviewer_result({"reviewer": "g", "findings": [_raw(severity="high")]},
                              strict=True)
    f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [_raw(line="42")]},
                                    strict=True)
    assert f[0].line == "42"
    with pytest.raises(ContractError, match="not an object"):
        parse_reviewer_result({"reviewer": "g", "findings": ["junk"]}, strict=True)


def test_missing_reviewer_always_raises():
    with pytest.raises(ContractError, match="reviewer"):
        parse_reviewer_result({"findings": []})


def test_rule_id_explicit_then_inferred_then_clone_none():
    f, _, _ = parse_reviewer_result({"reviewer": "g", "findings": [
        _raw(id="GEN-001-2"),
        _raw(id="X-9", rule_id="GEN-004"),
        _raw(id="CLONE-bob-001"),
        _raw(id="CLONE-123-001"),
        _raw(id="free text", rule_id="not valid"),
    ]})
    assert [x.rule_id for x in f] == ["GEN-001", "GEN-004", None, None, None]
    assert RULE_ID_RE.match("GEN-001-2")


def _mk(line, actual="except: pass", id_="GEN-001"):
    return Finding(reviewer="general", id=id_, file="a.py", rule="r", actual=actual,
                   severity="error", category="c", suggestion="s", line=line,
                   rule_id="GEN-001")


def _fps(findings):
    return [f.fingerprint for f in assign_fingerprints(findings)]


def test_fingerprint_is_line_free_and_normalised():
    a, b = _fps([_mk(1)])[0], _fps([_mk(99, actual="  EXCEPT:   pass ")])[0]
    assert a == b and a.startswith("f") and len(a) == 12


def test_fingerprint_differs_on_file_reviewer_rule():
    base = _mk(1)
    others = [replace(base, file="b.py"), replace(base, reviewer="x"),
              replace(base, rule_id="GEN-002")]
    fps = {_fps([base])[0]} | {_fps([o])[0] for o in others}
    assert len(fps) == 4


def test_fingerprint_collision_gets_ordinal_ordered_by_line():
    fps = _fps([_mk(30, id_="B"), _mk(10, id_="A"), _mk(20, id_="C")])
    base = fps[1]
    assert fps == [f"{base}-3", base, f"{base}-2"]


def test_fingerprint_collision_keeps_both_findings_distinct():
    fs = assign_fingerprints([_mk(10), _mk(20)])
    assert len({f.fingerprint for f in fs}) == 2


def test_fingerprint_existing_kept_and_not_reused():
    first = assign_fingerprints([_mk(1)])[0]
    out = assign_fingerprints([first, _mk(2)])
    assert out[0].fingerprint == first.fingerprint
    assert out[1].fingerprint == f"{first.fingerprint}-2"


def test_finding_dict_round_trip_ignores_unknown_keys():
    f = assign_fingerprints([_mk(3)])[0]
    d = finding_to_dict(f)
    d["surprise"] = 1
    assert finding_from_dict(d) == f


def test_report_shows_fingerprint_and_refuted_section():
    kept = assign_fingerprints([_mk(1)])
    gone = assign_fingerprints([_mk(7, actual="other")])
    gone = [replace(gone[0], verdict="refuted", reason="guarded on line\n3")]
    out = render_report(collate(kept), {"strategy": "adversarial", "scope": "changed",
                                        "notes": ["unverified: fabc"]}, gone)
    assert f"fingerprint: `{kept[0].fingerprint}`" in out
    assert "1 refuted" in out
    head, tail = out.split("## Refuted (dropped by critic)")
    assert gone[0].fingerprint in tail and "a.py:7" in tail and "guarded on line 3" in tail
    assert "other" not in head
    assert "## Notes" in head and "unverified: fabc" in head


def test_report_without_dropped_has_no_refuted_section():
    out = render_report(collate([_mk(1)]), {})
    assert "efuted" not in out
