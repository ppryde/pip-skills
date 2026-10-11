from dataclasses import replace

from scripts.contract import Finding, apply_verdicts, assign_fingerprints
from scripts.reconcile import merge_verdicts, reconcile


def _f(id_="GEN-001", severity="error", verdict=None, **kw):
    base = dict(reviewer="general", id=id_, file="a.py", rule="r", actual="x",
                severity=severity, category="c", suggestion="s", line=1,
                rule_id=id_, verdict=verdict)
    base.update(kw)
    return Finding(**base)


def test_no_verdict_and_confirmed_are_kept():
    r = apply_verdicts([_f(), _f("GEN-002", verdict="confirmed")])
    assert [f.id for f in r.kept] == ["GEN-001", "GEN-002"]
    assert r.dropped == [] and r.notes == []


def test_refuted_is_dropped_not_lost():
    r = apply_verdicts([_f(verdict="refuted", reason="not real")])
    assert r.kept == []
    assert r.dropped[0].reason == "not real"


def test_weakened_steps_down_and_records_before():
    r = apply_verdicts([_f(severity="error", verdict="weakened"),
                        _f("GEN-002", severity="warning", verdict="weakened")])
    assert [f.severity for f in r.kept] == ["warning", "info"]
    assert [f.severity_before for f in r.kept] == ["error", "warning"]


def test_weakened_info_stays_info():
    r = apply_verdicts([_f(severity="info", verdict="weakened")])
    assert r.kept[0].severity == "info"
    assert r.kept[0].severity_before is None


def test_apply_verdicts_is_idempotent():
    once = apply_verdicts([_f(severity="error", verdict="weakened")])
    twice = apply_verdicts(once.kept)
    assert twice.kept[0].severity == "warning"
    assert twice.kept[0].severity_before == "error"


def test_require_notes_missing_verdict_but_keeps_it():
    f = assign_fingerprints([_f()])
    r = apply_verdicts(f, require=True)
    assert len(r.kept) == 1
    assert r.notes == [f"unverified: {f[0].fingerprint}"]


def test_without_require_missing_verdict_is_silent():
    assert apply_verdicts([_f()]).notes == []


def test_unknown_verdict_kept_and_noted():
    r = apply_verdicts([_f(verdict="maybe")])
    assert len(r.kept) == 1
    assert "unknown verdict 'maybe'" in r.notes[0]


def test_input_list_and_findings_not_mutated():
    items = [_f(severity="error", verdict="weakened"), _f("GEN-002", verdict="refuted")]
    before = [replace(f) for f in items]
    apply_verdicts(items)
    assert items == before


def test_merge_verdicts_stamps_by_fingerprint_and_notes_unknown():
    fs = assign_fingerprints([_f(), _f("GEN-002", actual="y")])
    out, notes = merge_verdicts(fs, {
        fs[0].fingerprint: {"verdict": "refuted", "reason": "nope"},
        "fdeadbeef0000": {"verdict": "confirmed"},
    })
    assert out[0].verdict == "refuted" and out[0].reason == "nope"
    assert out[1].verdict is None
    assert notes == ["verdict for unknown fingerprint: fdeadbeef0000"]


def test_merge_verdicts_malformed_entry_noted():
    fs = assign_fingerprints([_f()])
    out, notes = merge_verdicts(fs, {fs[0].fingerprint: "refuted"})
    assert out[0].verdict is None
    assert "malformed" in notes[0]


def test_reconcile_order_weakened_error_stays_warning_after_pragmatic():
    # pragmatic + listed exception would soften error->warning; a weakened error
    # is already warning and must not be lowered twice or raised back.
    fs = [_f(severity="error", verdict="weakened")]
    res = reconcile(fs, strictness={"general": "pragmatic"},
                    exceptions={"general": {"GEN-001"}})
    assert res.findings[0].severity == "warning"
    assert res.findings[0].severity_before == "error"


def test_reconcile_decision_wins_over_verdict_downgrade():
    fs = [_f(severity="error", verdict="weakened")]
    fp = assign_fingerprints(fs)[0].fingerprint
    res = reconcile(fs, decisions={"overrides": {fp: {"severity": "error", "reason": "owner"}}})
    assert res.findings[0].severity == "error"
    assert res.findings[0].reason == "owner"


def test_reconcile_refuted_never_reaches_strictness_and_is_dropped():
    res = reconcile([_f(verdict="refuted")])
    assert res.findings == [] and len(res.dropped) == 1


def test_reconcile_require_verdicts_collects_unverified_notes():
    res = reconcile([_f(), _f("GEN-002", actual="y", verdict="confirmed")],
                    require_verdicts=True)
    assert len(res.findings) == 2
    assert sum(n.startswith("unverified:") for n in res.notes) == 1


def test_reconcile_applies_verdict_map():
    fs = assign_fingerprints([_f()])
    res = reconcile(fs, verdicts={fs[0].fingerprint: {"verdict": "refuted", "reason": "r"}})
    assert res.findings == [] and res.dropped[0].reason == "r"
