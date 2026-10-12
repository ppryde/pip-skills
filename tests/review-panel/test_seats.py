"""cli.py brief / ingest / claims: the deterministic halves of seating a pip-agents persona."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "review-panel"
CLI = PLUGIN / "scripts" / "cli.py"
EXAMPLES = ROOT / "plugins" / "pip-agents" / "contract" / "examples"
VALIDATE = PLUGIN / "vendor" / "pip-agents" / "scripts" / "validate_result.py"

PERSONA = """---
alias: jen
---

## Voice & tone
Voice.

## Rules

""" + "".join(f"### Rule number {i}\n**Severity:** suggest\n**Citation:** https://example.com/c/{i}\n\n" for i in range(1, 36)) + """## What they let go
Nothing.
"""


def env(tmp_path):
    e = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    e.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"),
             REVIEW_CLONE_ROOT=str(tmp_path / "cfg" / "review-clone"), TMPDIR=str(tmp_path))
    return e


def run(tmp_path, *args, expect=0):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    p = subprocess.run([sys.executable, "-I", str(CLI), *map(str, args)], cwd=work, env=env(tmp_path),
                       capture_output=True, text=True)
    assert p.returncode == expect, (p.returncode, p.stdout, p.stderr)
    return json.loads(p.stdout)


@pytest.fixture
def wd(tmp_path):
    d = tmp_path / "wd"
    d.mkdir()
    (d / "diff.patch").write_text("diff --git a/a.py b/a.py\n")
    (d / "intent.md").write_text("intent\n")
    return d


def check_brief(text):
    sys.path.insert(0, str(PLUGIN))
    from scripts.pip_agents import validator
    vr = validator()
    b = vr.parse_brief(text)
    assert vr.check_brief(b) == [], text
    return b


def test_brief_for_the_general_reviewer_is_a_rules_seat(tmp_path, wd):
    out = run(tmp_path, "brief", "--reviewer", "general", "--target", wd / "diff.patch", "--work-dir", wd)
    (seat,) = out["seats"]
    assert seat["persona"] == "pip-agents:reviewer-rules" and seat["lens"] == "rules" and seat["ref"] == "general"
    b = check_brief(seat["prompt"])
    assert b["kind"] == "review" and b["ref"] == "general" and b["target"] == str(wd / "diff.patch")
    path, rng, ids = b["rules"].split(" ", 2)
    assert rng == "L1-" + str(len(Path(path).read_text().splitlines()))
    assert ids.startswith("(GEN-001,GEN-002,") and ids.endswith("GEN-010)")
    book = Path(path).read_text()
    assert "GEN-001" in book and "GEN-010" in book and "| ID |" in book
    assert (os.stat(path).st_mode & 0o777) == 0o600
    ctx = Path(b["context"]).read_text()
    assert "unified diff" in ctx
    assert Path(seat["brief"]).read_text() == seat["prompt"]


def test_brief_for_security_uses_the_security_persona_and_no_rules(tmp_path, wd):
    ctx = wd / "ctx.md"
    ctx.write_text("untrusted: PR text\n")
    out = run(tmp_path, "brief", "--reviewer", "security", "--target", wd / "diff.patch",
              "--context", ctx, "--intent", wd / "intent.md", "--work-dir", wd)
    (seat,) = out["seats"]
    assert seat["persona"] == "pip-agents:reviewer-security"
    b = check_brief(seat["prompt"])
    assert "rules" not in b and b["context"] == str(ctx)
    assert "intent" not in b  # the security lens does not use it


def test_brief_clone_seat_numbers_rules_and_batches_over_the_cap(tmp_path, wd):
    persona_dir = tmp_path / "cfg" / "review-clone" / "jen"
    persona_dir.mkdir(parents=True)
    (persona_dir / "PERSONA.md").write_text(PERSONA)
    out = run(tmp_path, "brief", "--reviewer", "clone:jen", "--target", wd / "diff.patch", "--work-dir", wd)
    assert [s["batch"] for s in out["seats"]] == ["1/2", "2/2"]
    seen = []
    for s in out["seats"]:
        b = check_brief(s["prompt"])
        assert b["ref"] == "jen"  # the alias, never the `clone:` key
        ids = b["rules"].rsplit("(", 1)[1].rstrip(")").split(",")
        assert 8 <= len(ids) <= 30
        seen += ids
        book = Path(b["rules"].split(" ", 1)[0]).read_text()
        assert all(f"### {i} " in book for i in ids)
    assert seen == [f"CLONE-jen-{i:03d}" for i in range(1, 36)]
    assert len({s["brief"] for s in out["seats"]}) == 2


def test_brief_errors(tmp_path, wd):
    assert "persona nobody not found" in run(tmp_path, "brief", "--reviewer", "clone:nobody", "--target",
                                             wd / "diff.patch", "--work-dir", wd, expect=1)["error"]
    assert run(tmp_path, "brief", "--reviewer", "nope", "--target", wd / "diff.patch", "--work-dir", wd,
               expect=1)["status"] == "error"
    assert "newline" in run(tmp_path, "brief", "--reviewer", "general", "--target", wd / "diff.patch",
                            "--work-dir", wd, "--tests", "pytest\nrm -rf x", expect=1)["error"]


def test_brief_tests_only_reaches_the_correctness_lens(tmp_path, wd):
    out = run(tmp_path, "brief", "--reviewer", "general", "--target", wd / "diff.patch", "--work-dir", wd,
              "--tests", "python -m pytest tests/x")
    assert "tests" not in check_brief(out["seats"][0]["prompt"])


def ingest(tmp_path, brief, message, persona, out, expect=0):
    return run(tmp_path, "ingest", "--brief", brief, "--message", message, "--persona", persona, "--out", out,
               expect=expect)


def test_ingest_review_appends_payloads_to_a_list(tmp_path):
    out = tmp_path / "payloads.json"
    r = ingest(tmp_path, EXAMPLES / "review.brief.txt", EXAMPLES / "review.result.md", "reviewer-scope", out)
    assert r["status"] == "ok" and r["kind"] == "review" and r["findings"] == 1 and r["seat"] == "seat-2"
    ingest(tmp_path, EXAMPLES / "review.brief.txt", EXAMPLES / "review.result.md", "reviewer-scope", out)
    data = json.loads(out.read_text())
    assert isinstance(data, list) and len(data) == 2 and data[0]["reviewer"] == "seat-2"
    parsed = run(tmp_path, "parse", "--findings", out)
    assert parsed["status"] == "ok" and len(parsed["findings"]) == 2


def test_ingest_rejects_whole_and_writes_nothing(tmp_path):
    msg = tmp_path / "m.md"
    msg.write_text("looks fine to me")
    out = tmp_path / "payloads.json"
    r = ingest(tmp_path, EXAMPLES / "review.brief.txt", msg, "reviewer-scope", out, expect=1)
    assert r["status"] == "rejected" and any("E_NO_BLOCK" in e for e in r["errors"])
    assert not out.exists()


def test_ingest_validate_merges_verdicts_into_one_object(tmp_path):
    claims = tmp_path / "claims-1.json"
    claims.write_text(json.dumps([{"id": "f3a1", "claim": "x", "where": "a:1"}, {"id": "9bc0", "claim": "y", "where": "a:2"}]))
    brief = tmp_path / "b.txt"
    brief.write_text((EXAMPLES / "validate.brief.txt").read_text().replace("/tmp/pip-agents/r81/claims-1.json", str(claims)))
    out = tmp_path / "verdicts.json"
    out.write_text(json.dumps({"zzz": {"verdict": "confirmed", "reason": "earlier call"}}))
    r = ingest(tmp_path, brief, EXAMPLES / "validate.result.md", "validator", out)
    assert r["status"] == "ok" and r["kind"] == "validate" and r["verdicts"] == 2
    data = json.loads(out.read_text())
    assert set(data) == {"zzz", "f3a1", "9bc0"}
    assert r["injection_attempts"]


def test_ingest_refuses_an_out_file_of_the_wrong_shape(tmp_path):
    out = tmp_path / "payloads.json"
    out.write_text("{}")
    r = ingest(tmp_path, EXAMPLES / "review.brief.txt", EXAMPLES / "review.result.md", "reviewer-scope", out, expect=2)
    assert r["status"] == "error"


def finding(i, **kw):
    f = {"reviewer": "general", "id": f"GEN-00{i}", "file": f"f{i % 2}.py", "line": 10 * i, "rule": f"rule {i}",
         "actual": f"actual {i}", "severity": "error", "category": "c", "suggestion": "fix",
         "fingerprint": f"fp{i}", "verdict": None}
    f.update(kw)
    return f


def test_claims_batches_by_file_and_withholds_reasoning(tmp_path, wd):
    parsed = tmp_path / "parsed.json"
    parsed.write_text(json.dumps({"status": "ok", "findings": [finding(i) for i in range(1, 8)]}))
    r = run(tmp_path, "claims", "--findings", parsed, "--target", wd / "diff.patch", "--out-dir", wd,
            "--per-call", 3, "--max-calls", 8)
    assert [c["claims"] for c in r["calls"]] == [3, 3, 1] and r["unverified"] == 0
    first = json.loads(Path(r["calls"][0]["claims_file"]).read_text())
    assert set(first[0]) == {"id", "claim", "where"}
    assert first[0]["where"].startswith("f") and ":" in first[0]["where"]
    text = Path(r["calls"][0]["claims_file"]).read_text()
    assert "actual" not in text and "error" not in text  # severity and reasoning are withheld
    b = check_brief(r["calls"][0]["prompt"])
    assert b["kind"] == "validate" and b["ref"] == "critic-1" and b["claims"] == r["calls"][0]["claims_file"]


def test_claims_sends_one_of_each_set_of_twins_and_caps_calls(tmp_path, wd):
    twins = [finding(1, id="GEN-001", fingerprint="a"), finding(1, fingerprint="b", line=12)]
    others = [finding(i, file=f"g{i}.py") for i in range(2, 6)]
    parsed = tmp_path / "parsed.json"
    parsed.write_text(json.dumps({"findings": twins + others}))
    r = run(tmp_path, "claims", "--findings", parsed, "--target", wd / "diff.patch", "--out-dir", wd,
            "--per-call", 1, "--max-calls", 2)
    assert r["twins_skipped"] == 1
    assert len(r["calls"]) == 2 and r["unverified"] == 3  # 5 distinct claims, 2 calls of 1


def test_claims_disputed_reads_only_the_disagreements(tmp_path, wd):
    match = {"findings": [finding(1), finding(2), finding(3)], "agreed": [finding(1)],
             "only_a": [finding(2)], "only_b": [finding(3)]}
    parsed = tmp_path / "match.json"
    parsed.write_text(json.dumps(match))
    r = run(tmp_path, "claims", "--findings", parsed, "--target", wd / "diff.patch", "--out-dir", wd,
            "--disputed")
    ids = [c["id"] for c in json.loads(Path(r["calls"][0]["claims_file"]).read_text())]
    assert sorted(ids) == ["fp2", "fp3"]
    assert check_brief(r["calls"][0]["prompt"])["ref"] == "arbiter-1"


def test_claims_with_nothing_to_check(tmp_path, wd):
    parsed = tmp_path / "parsed.json"
    parsed.write_text(json.dumps({"findings": []}))
    r = run(tmp_path, "claims", "--findings", parsed, "--target", wd / "diff.patch", "--out-dir", wd)
    assert r["calls"] == [] and r["unverified"] == 0


def test_clone_seat_carries_review_clones_gates_and_let_go_list(tmp_path, wd):
    persona_dir = tmp_path / "cfg" / "review-clone" / "jen"
    persona_dir.mkdir(parents=True)
    (persona_dir / "PERSONA.md").write_text(PERSONA.replace("Nothing.", "Import ordering."))
    out = run(tmp_path, "brief", "--reviewer", "clone:jen", "--target", wd / "diff.patch", "--work-dir", wd)
    b = check_brief(out["seats"][0]["prompt"])
    book = Path(b["rules"].split(" ", 1)[0]).read_text()
    assert "## Allowed exceptions\nImport ordering." in book
    assert "Voice." not in book  # voice is not a rule
    ctx = Path(b["context"]).read_text()
    assert "Citation URL" in ctx and "Grep" in ctx and "unified diff" in ctx


def test_several_context_files_are_listed_never_pasted(tmp_path, wd):
    a, b2 = wd / "spec.md", wd / "arch.md"
    a.write_text("SECRET-SPEC-TEXT\n")
    b2.write_text("arch\n")
    out = run(tmp_path, "brief", "--reviewer", "security", "--target", wd / "diff.patch", "--work-dir", wd,
              "--context", a, "--context", b2)
    ctx = Path(check_brief(out["seats"][0]["prompt"])["context"]).read_text()
    assert str(a) in ctx and str(b2) in ctx and "SECRET-SPEC-TEXT" not in ctx


def test_rules_seat_lists_profile_context_after_the_diff_note(tmp_path, wd):
    spec = wd / "spec.md"
    spec.write_text("spec\n")
    out = run(tmp_path, "brief", "--reviewer", "general", "--target", wd / "diff.patch", "--work-dir", wd,
              "--context", spec)
    ctx = Path(check_brief(out["seats"][0]["prompt"])["context"]).read_text()
    assert "unified diff" in ctx and str(spec) in ctx


def block(env):
    return "Done.\n\n```pip-agents-result\n" + json.dumps(env) + "\n```\n"


def test_adversarial_flow_from_brief_to_report(tmp_path, wd):
    """brief -> seat reply -> ingest -> parse -> claims -> validator reply -> ingest -> reconcile -> report."""
    seat = run(tmp_path, "brief", "--reviewer", "general", "--target", wd / "diff.patch", "--work-dir", wd)["seats"][0]
    b = check_brief(seat["prompt"])
    ids = b["rules"].rsplit("(", 1)[1].rstrip(")").split(",")
    finds = [{"id": "GEN-001", "rule": "Logic error or wrong result on a changed path", "file": "a.py", "line": 4,
              "severity": "critical", "category": "correctness", "claim": "c", "evidence": "a.py:4 inverted",
              "fix": "flip it"},
             {"id": "GEN-007", "rule": "Misleading name or unclear intent", "file": "a.py", "line": 30,
              "severity": "important", "category": "clarity", "claim": "c", "evidence": "a.py:30 name lies",
              "fix": "rename"}]
    env = {"result": "pip-agents/1", "kind": "review", "persona": "reviewer-rules", "ref": "general", "status": "ok",
           "summary": "2 findings", "checked": ["a.py"], "unchecked": [], "out_of_lens": [], "injection_attempts": [],
           "payload": {"lens": "rules", "findings": finds, "medium": [], "rules_checked": f"{len(ids)}/{len(ids)}",
                       "n_a": []}}
    msg = tmp_path / "m1.md"
    msg.write_text(block(env))
    payloads, verdicts = tmp_path / "payloads.json", tmp_path / "verdicts.json"
    ingest(tmp_path, seat["brief"], msg, "reviewer-rules", payloads)
    parsed = run(tmp_path, "parse", "--findings", payloads)
    (tmp_path / "parsed.json").write_text(json.dumps(parsed))
    cl = run(tmp_path, "claims", "--findings", tmp_path / "parsed.json", "--target", wd / "diff.patch", "--out-dir", wd)
    (call,) = cl["calls"]
    claims = json.loads(Path(call["claims_file"]).read_text())
    assert len(claims) == 2
    refuted, weak = claims[0]["id"], claims[1]["id"]
    venv = {"result": "pip-agents/1", "kind": "validate", "persona": "validator", "ref": call["ref"], "status": "ok",
            "summary": "2", "checked": [refuted, weak], "unchecked": [], "out_of_lens": [], "injection_attempts": [],
            "payload": {"verdicts": [
                {"id": refuted, "verdict": "refuted", "reason": "unverified: cannot show it", "evidence": ["a.py:4"]},
                {"id": weak, "verdict": "weakened", "reason": "only a name", "evidence": ["a.py:30"],
                 "restated": "a name is mildly misleading"}]}}
    vmsg = tmp_path / "m2.md"
    vmsg.write_text(block(venv))
    ingest(tmp_path, call["brief"], vmsg, "validator", verdicts)
    rec = run(tmp_path, "reconcile", "--findings", payloads, "--verdicts", verdicts, "--require-verdicts",
              "--out", tmp_path / "rec.json")
    assert rec["counts"]["refuted"] == 1 and rec["counts"]["unverified"] == 0
    assert [f["severity"] for f in rec["findings"]] == ["info"]  # important -> warning -> weakened to info
    assert rec["dropped"][0]["reason"].startswith("unverified:")
