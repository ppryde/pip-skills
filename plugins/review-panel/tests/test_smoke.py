"""End-to-end smoke over the deterministic pipeline the orchestrator uses:
resolve a profile -> parse a (mocked) reviewer result -> strictness ->
decisions -> collate -> render. No live subagent, no git, no gh."""
import textwrap
from pathlib import Path

from scripts.config import load_config, resolve_profile
from scripts.contract import parse_reviewer_result, collate, render_report
from scripts.strictness import apply_strictness, apply_decisions


def test_pipeline_produces_report(tmp_path):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(textwrap.dedent("""
        defaults: { strategy: committee, scope: changed, profile: pre-merge }
        profiles:
          pre-merge: { reviewers: { general: strict } }
        output: { default: report }
    """))
    resolved = resolve_profile(load_config(cfg_path), None)
    assert resolved.strategy == "committee"

    # A reviewer subagent would return this; here we mock it.
    mocked = {
        "reviewer": "general",
        "findings": [
            {"id": "GEN-001", "file": "app.py", "line": 12, "rule": "null deref",
             "actual": "user.name", "severity": "error", "category": "correctness",
             "suggestion": "guard user"},
        ],
        "clean_files": ["util.py"],
        "notes": [],
    }
    findings, _clean, _notes = parse_reviewer_result(mocked)

    strictness = {r.name: r.strictness for r in resolved.reviewers}
    findings = apply_strictness(findings, strictness)
    findings = apply_decisions(findings, {})
    report = render_report(collate(findings), {"strategy": resolved.strategy, "scope": resolved.scope})

    assert "GEN-001" in report
    assert "1 error" in report
    assert "committee" in report


def test_full_suite_importable():
    import scripts.config, scripts.discovery, scripts.contract  # noqa: F401
    import scripts.strictness, scripts.personas, scripts.doclint  # noqa: F401
