import textwrap
from pathlib import Path

from scripts.contract import Finding
from scripts.strictness import apply_strictness, load_decisions, apply_decisions


def _f(id_, reviewer="general", severity="error"):
    return Finding(reviewer=reviewer, id=id_, file="a.py", rule="r",
                   actual="x", severity=severity, category="c", suggestion="s")


def test_strict_keeps_severity():
    out = apply_strictness([_f("G1")], {"general": "strict"})
    assert out[0].severity == "error"


def test_aspirational_downgrades_everything():
    out = apply_strictness([_f("G1"), _f("G2", severity="info")], {"general": "aspirational"})
    assert [f.severity for f in out] == ["warning", "warning"]


def test_pragmatic_downgrades_only_allowed_exceptions():
    out = apply_strictness(
        [_f("G1"), _f("G2")],
        {"general": "pragmatic"},
        allowed_exceptions={"general": {"G2"}},
    )
    sev = {f.id: f.severity for f in out}
    assert sev == {"G1": "error", "G2": "warning"}


def test_default_strictness_is_pragmatic():
    out = apply_strictness([_f("G1")], {})  # missing reviewer -> pragmatic
    assert out[0].severity == "error"


def test_decisions_override_by_id(tmp_path):
    p = tmp_path / "decisions.yml"
    p.write_text(textwrap.dedent("""
        overrides:
          G1: { severity: info, reason: "team decision" }
    """))
    decisions = load_decisions(p)
    out = apply_decisions([_f("G1"), _f("G2")], decisions)
    by_id = {f.id: f for f in out}
    assert by_id["G1"].severity == "info"
    assert by_id["G1"].reason == "team decision"
    assert by_id["G2"].severity == "error"


def test_load_decisions_missing_is_empty(tmp_path):
    assert load_decisions(tmp_path / "absent.yml") == {}
