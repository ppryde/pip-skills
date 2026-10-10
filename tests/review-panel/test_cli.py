"""The CLI is run as a script with PYTHONPATH unset, from an empty cwd, to
prove it bootstraps its own imports. HOME/CLAUDE_CONFIG_DIR are pinned into
tmp_path (see the conftest autouse fixture for the in-process pins)."""
import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "review-panel"
CLI = PLUGIN / "scripts" / "cli.py"


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"),
               REVIEW_CLONE_ROOT=str(tmp_path / "cfg" / "review-clone"))
    return env


def run(tmp_path, *args, expect=0):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    p = subprocess.run([sys.executable, "-I", str(CLI), *map(str, args)],
                       cwd=work, env=_env(tmp_path), capture_output=True, text=True)
    assert p.returncode == expect, (p.returncode, p.stdout, p.stderr)
    return p


def j(tmp_path, *args, expect=0):
    return json.loads(run(tmp_path, *args, expect=expect).stdout)


def _raw(i, **kw):
    base = {"id": f"GEN-00{i}", "file": "a.py", "line": i, "rule": f"rule {i}",
            "actual": f"actual {i}", "severity": "error", "category": "c",
            "suggestion": "fix", "rule_id": f"GEN-00{i}"}
    base.update(kw)
    return base


def _write(path, data):
    path.write_text(json.dumps(data))
    return path


def test_resolve_lists(tmp_path):
    assert "general" in j(tmp_path, "resolve", "--list", "reviewers")["reviewers"]
    assert "committee" in j(tmp_path, "resolve", "--list", "strategies")["strategies"]


def test_resolve_config_missing_is_status_not_traceback(tmp_path):
    out = j(tmp_path, "resolve", "--config", tmp_path / "nope.yml", expect=3)
    assert out["status"] == "config-missing"


def test_resolve_profile_with_overrides(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "defaults: { strategy: committee, scope: changed, profile: pre-merge }\n"
        "profiles:\n  pre-merge: { reviewers: { general: strict } }\n")
    out = j(tmp_path, "resolve", "--config", cfg, "--scope", "full", "--output", "inline")
    review = out["review"]
    assert review["scope"] == "full" and review["output"] == "inline"
    assert review["reviewers"][0] == {"key": "general", "source": "builtin",
                                      "name": "general", "strictness": "strict"}


def test_resolve_adhoc_and_bad_profile(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("profiles:\n  a: { reviewers: { general: strict } }\n")
    out = j(tmp_path, "resolve", "--config", cfg, "--reviewer", "general")
    assert out["review"]["reviewers"][0]["strictness"] == "pragmatic"
    bad = j(tmp_path, "resolve", "--config", cfg, "--profile", "zzz", expect=1)
    assert bad["status"] == "error" and "unknown profile" in bad["error"]


def test_parse_assigns_fingerprints_and_reports_rejects(tmp_path):
    f = _write(tmp_path / "f.json", [
        {"reviewer": "general", "findings": [_raw(1), {"id": "x"}]}])
    out = j(tmp_path, "parse", "--findings", f)
    assert out["findings"][0]["fingerprint"].startswith("f")
    assert any(n.startswith("REJECTED x:") for n in out["notes"])


def test_reconcile_end_to_end_with_verdicts(tmp_path):
    payloads = _write(tmp_path / "f.json", [
        {"reviewer": "general", "findings": [_raw(1), _raw(2), _raw(3, severity="warning")]}])
    parsed = j(tmp_path, "parse", "--findings", payloads)["findings"]
    fp = {f["id"]: f["fingerprint"] for f in parsed}
    verdicts = _write(tmp_path / "v.json", {
        fp["GEN-001"]: {"verdict": "refuted", "reason": "guarded"},
        fp["GEN-002"]: {"verdict": "weakened", "reason": "edge"},
        "fnotafingerprint": {"verdict": "confirmed"},
    })
    out = j(tmp_path, "reconcile", "--findings", payloads, "--verdicts", verdicts,
            "--require-verdicts", "--strictness", "general=strict")
    by_id = {f["id"]: f for f in out["findings"]}
    assert set(by_id) == {"GEN-002", "GEN-003"}
    assert by_id["GEN-002"]["severity"] == "warning"
    assert by_id["GEN-002"]["severity_before"] == "error"
    assert [d["id"] for d in out["dropped"]] == ["GEN-001"]
    assert out["counts"] == {"error": 0, "warning": 2, "info": 0, "refuted": 1,
                             "unverified": 1}
    assert any("unknown fingerprint" in n for n in out["notes"])
    assert any(n == f"unverified: {fp['GEN-003']}" for n in out["notes"])


def test_reconcile_missing_verdicts_file_is_tolerated(tmp_path):
    payloads = _write(tmp_path / "f.json", {"reviewer": "general", "findings": [_raw(1)]})
    out = j(tmp_path, "reconcile", "--findings", payloads,
            "--verdicts", tmp_path / "absent.json")
    assert len(out["findings"]) == 1
    assert len(out["notes"]) == 1 and "verdicts file not found" in out["notes"][0]


def test_reconcile_applies_exceptions_decisions_and_legacy_note(tmp_path):
    # GEN-009 is not an exception in the shipped general.md, so use a custom dir.
    rdir = tmp_path / "reviewers"
    rdir.mkdir()
    (rdir / "general.md").write_text("```allowed-exceptions\nGEN-004   # fine\n```\n")
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [
        _raw(4), _raw(1)]}])
    dec = tmp_path / "decisions.yml"
    dec.write_text("overrides:\n  GEN-001: { severity: info, reason: owner }\n")
    out = j(tmp_path, "reconcile", "--findings", payloads, "--reviewers-dir", rdir,
            "--decisions", dec)
    sev = {f["id"]: f["severity"] for f in out["findings"]}
    assert sev == {"GEN-004": "warning", "GEN-001": "info"}
    assert "legacy id-keyed override matched: GEN-001; migrate" in out["notes"]


def test_reconcile_warns_on_custom_reviewer_without_block(tmp_path):
    rdir = tmp_path / "reviewers"
    rdir.mkdir()
    (rdir / "general.md").write_text("## Allowed exceptions\nprose only\n")
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [_raw(1)]}])
    out = j(tmp_path, "reconcile", "--findings", payloads, "--reviewers-dir", rdir)
    assert any("general.md" in n and "no exceptions" in n for n in out["notes"])


def test_reconcile_rejects_bad_strictness_and_bad_json(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": []}])
    bad = j(tmp_path, "reconcile", "--findings", payloads, "--strictness", "general=lax",
            expect=2)
    assert bad["status"] == "error"
    broken = tmp_path / "broken.json"
    broken.write_text("{nope")
    assert j(tmp_path, "reconcile", "--findings", broken, expect=2)["status"] == "error"
    assert j(tmp_path, "reconcile", "--findings", tmp_path / "gone.json",
             expect=2)["status"] == "error"


def test_report_renders_refuted_section_and_writes_relative_file(tmp_path):
    payloads = _write(tmp_path / "f.json", [{"reviewer": "general", "findings": [
        _raw(1), _raw(2)]}])
    parsed = _write(tmp_path / "p.json", j(tmp_path, "parse", "--findings", payloads))
    fp2 = json.loads(parsed.read_text())["findings"][1]["fingerprint"]
    verdicts = _write(tmp_path / "v.json", {fp2: {"verdict": "refuted", "reason": "not real"}})
    rec = tmp_path / "rec.json"
    run(tmp_path, "reconcile", "--findings", parsed, "--verdicts", verdicts, "--out", rec)
    p = run(tmp_path, "report", "--reconciled", rec, "--strategy", "adversarial",
            "--scope", "changed", "--out", ".review-panel/last-review.md")
    assert "## Refuted (dropped by critic)" in p.stdout and "not real" in p.stdout
    assert "1 refuted" in p.stdout
    written = tmp_path / "work" / ".review-panel" / "last-review.md"
    assert written.read_text() == p.stdout


def test_report_refuses_escaping_output_path(tmp_path):
    rec = _write(tmp_path / "rec.json", {"findings": [], "dropped": []})
    for bad in ("../x.md", str(tmp_path / "abs.md")):
        out = j(tmp_path, "report", "--reconciled", rec, "--out", bad, expect=2)
        assert out["status"] == "error"
    assert not (tmp_path / "x.md").exists() and not (tmp_path / "abs.md").exists()


def test_match_then_reconcile_dual_tiebreaker(tmp_path):
    a = _write(tmp_path / "a.json", [{"reviewer": "general", "findings": [
        _raw(1, line=10), _raw(2, line=50)]}])
    b = _write(tmp_path / "b.json", [{"reviewer": "general", "findings": [
        _raw(1, line=12, id="GEN-001"), _raw(3, line=90)]}])
    m = j(tmp_path, "match", "--a", a, "--b", b)
    assert [f["id"] for f in m["agreed"]] == ["GEN-001"]
    assert [f["id"] for f in m["only_a"]] == ["GEN-002"]
    assert [f["id"] for f in m["only_b"]] == ["GEN-003"]
    assert list(m["verdicts"]) == [m["agreed"][0]["fingerprint"]]
    assert m["verdicts"][m["agreed"][0]["fingerprint"]]["reason"] == "both passes"
    allfps = [f["fingerprint"] for k in ("agreed", "only_a", "only_b") for f in m[k]]
    assert len(set(allfps)) == 3
    matchfile = _write(tmp_path / "m.json", m)
    verdicts = _write(tmp_path / "v.json", {
        **m["verdicts"],
        m["only_a"][0]["fingerprint"]: {"verdict": "refuted", "reason": "no"},
        m["only_b"][0]["fingerprint"]: {"verdict": "confirmed", "reason": "yes"}})
    out = j(tmp_path, "reconcile", "--findings", matchfile, "--verdicts", verdicts,
            "--require-verdicts")
    assert sorted(f["id"] for f in out["findings"]) == ["GEN-001", "GEN-003"]
    assert out["counts"]["refuted"] == 1 and out["counts"]["unverified"] == 0


def test_cli_does_not_depend_on_cwd_or_pythonpath(tmp_path):
    p = subprocess.run([sys.executable, "-I", str(CLI), "--help"], cwd=tmp_path,
                       env=_env(tmp_path), capture_output=True, text=True)
    assert p.returncode == 0 and "reconcile" in p.stdout
