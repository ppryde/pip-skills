"""review-clone adopts pip-agents (WF-270 PR F): the collectors run through `pip-agents:gatekeeper` (a validated `run`
envelope, snapshot path + counts, never stdout), and review-as hands rule batches above 30 rules to
`pip-agents:reviewer-rules`. `scripts/gate.py` is the deterministic half of both."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "review-clone"
GATE = PLUGIN / "scripts" / "gate.py"
COLLECT = PLUGIN / "scripts" / "collect.py"


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "personas"
    root.mkdir()
    return root


def run(tmp_path, home, *args, expect=0):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"), REVIEW_CLONE_ROOT=str(home),
               TMPDIR=str(tmp_path))
    p = subprocess.run([sys.executable, "-I", str(GATE), *map(str, args)], cwd=tmp_path, env=env,
                       capture_output=True, text=True)
    assert p.returncode == expect, (p.returncode, p.stdout, p.stderr)
    return json.loads(p.stdout)


def vr():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate_test_vr", PLUGIN / "vendor/pip-agents/scripts/validate_result.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_test_vr"] = mod
    spec.loader.exec_module(mod)
    return mod


def collect_brief(tmp_path, home, *extra, expect=0):
    return run(tmp_path, home, "brief-collect", "--alias", "jen", "--handles", "jenniferjensen,bob", "--repo", "o/r",
               "--months", "6", "--paths", "frontend/,packages/", "--extensions", ".ts,.tsx",
               "--work-dir", tmp_path / "wd", *extra, expect=expect)


def test_collect_brief_is_a_valid_run_brief(tmp_path, home):
    out = collect_brief(tmp_path, home)
    assert out["persona"] == "pip-agents:gatekeeper" and out["status"] == "ok"
    b = vr().parse_brief(out["prompt"])
    assert vr().check_brief(b) == []
    assert b["kind"] == "run" and b["ref"] == "collect" and b["timeout_ms"] == 600000
    assert b["run"].startswith(f"python3 {COLLECT} --alias 'jen' --handles 'jenniferjensen,bob' --repo 'o/r' --months 6")
    assert "--paths='frontend/,packages/'" in b["run"] and "--extensions='.ts,.tsx'" in b["run"]
    assert b["out"] == str(home / "jen" / "snapshot.json") == out["out"]
    assert b["counts"] == "pr_count,comment_count,error_count"
    assert Path(out["brief"]).read_text() == out["prompt"]
    assert not any(c in b["run"] for c in "|;<>`") and "&&" not in b["run"] and "$(" not in b["run"]


def test_collect_brief_refresh_variants(tmp_path, home):
    inc = vr().parse_brief(collect_brief(tmp_path, home, "--incremental")["prompt"])
    assert inc["run"].endswith(" --incremental")
    since = vr().parse_brief(collect_brief(tmp_path, home, "--since", "2026-05-01T10:00:00Z")["prompt"])
    assert since["run"].endswith(" --since '2026-05-01T10:00:00Z'")


def test_empty_filters_are_passed_as_empty_strings(tmp_path, home):
    out = run(tmp_path, home, "brief-collect", "--alias", "jen", "--handles", "bob", "--repo", "o/r", "--months", "3",
              "--work-dir", tmp_path / "wd")
    run_line = vr().parse_brief(out["prompt"])["run"]
    assert "--paths=''" in run_line and "--extensions=''" in run_line


@pytest.mark.parametrize("flag,value", [
    ("--repo", "o/r; rm -rf ~"), ("--repo", "o/r/extra"), ("--handles", "bob,al ice"), ("--handles", "b$(x)"),
    ("--paths", "a|b"), ("--paths", "a;b"), ("--extensions", ".ts`id`"), ("--paths", "a\nb"),
    ("--since", "now; id"), ("--alias", "../x"), ("--alias", "Bad_Alias"), ("--months", "0"), ("--months", "7"),
])
def test_hostile_or_malformed_values_are_refused(tmp_path, home, flag, value):
    args = {"--alias": "jen", "--handles": "bob", "--repo": "o/r", "--months": "6", "--paths": "", "--extensions": ""}
    args[flag] = value
    flat = [x for kv in args.items() for x in kv]
    out = run(tmp_path, home, "brief-collect", *flat, "--work-dir", tmp_path / "wd", expect=1)
    assert out["status"] == "error" and not (tmp_path / "wd").exists()


def envelope(brief_text, **over):
    b = vr().parse_brief(brief_text)
    env = {"result": "pip-agents/1", "kind": "run", "persona": "gatekeeper", "ref": "collect", "status": "ok",
           "summary": "collector exited 0", "checked": [b["out"]], "unchecked": [], "out_of_lens": [],
           "injection_attempts": [],
           "payload": {"command": b["run"], "exit_code": 0, "timed_out": False, "out": b["out"],
                       "counts": {"pr_count": 57, "comment_count": 412, "error_count": 0}}}
    env.update(over)
    return env


def write(path, env):
    path.write_text("Done.\n\n```pip-agents-result\n" + json.dumps(env) + "\n```\n")
    return path


def check(tmp_path, home, brief, msg, expect=0):
    return run(tmp_path, home, "check-collect", "--brief", brief, "--message", msg, expect=expect)


def test_check_collect_accepts_a_good_run_and_names_the_snapshot(tmp_path, home):
    out = collect_brief(tmp_path, home)
    msg = write(tmp_path / "m.md", envelope(out["prompt"]))
    got = check(tmp_path, home, out["brief"], msg)
    assert got["status"] == "ok" and got["snapshot"] == out["out"]
    assert got["counts"] == {"pr_count": 57, "comment_count": 412, "error_count": 0}


def test_check_collect_reports_a_failed_collector(tmp_path, home):
    out = collect_brief(tmp_path, home)
    env = envelope(out["prompt"])
    env["payload"].update(exit_code=1, counts={"pr_count": 0, "comment_count": 0, "error_count": 0},
                          stderr_tail="error: no read access to o/r with your gh login")
    got = check(tmp_path, home, out["brief"], write(tmp_path / "m.md", env), expect=1)
    assert got["status"] == "failed" and got["exit_code"] == 1 and "no read access" in got["stderr_tail"]


def test_check_collect_reports_a_timeout_and_a_refusal(tmp_path, home):
    out = collect_brief(tmp_path, home)
    env = envelope(out["prompt"])
    env["payload"].update(exit_code=None, timed_out=True, stderr_tail="partial")
    assert check(tmp_path, home, out["brief"], write(tmp_path / "m.md", env), expect=1)["status"] == "failed"
    refused = envelope(out["prompt"], status="error", error="run: contains a metacharacter")
    refused.pop("payload")
    got = check(tmp_path, home, out["brief"], write(tmp_path / "m2.md", refused), expect=1)
    assert got["status"] == "refused" and "metacharacter" in got["error"]


def test_check_collect_rejects_an_altered_command_or_no_block(tmp_path, home):
    out = collect_brief(tmp_path, home)
    env = envelope(out["prompt"])
    env["payload"]["command"] += " --fresh"
    got = check(tmp_path, home, out["brief"], write(tmp_path / "m.md", env), expect=1)
    assert got["status"] == "rejected" and any("command" in e for e in got["errors"])
    (tmp_path / "n.md").write_text('{"alias": "jen"}')  # the old contract: raw JSON, not an envelope
    assert check(tmp_path, home, out["brief"], tmp_path / "n.md", expect=1)["status"] == "rejected"


def persona_text(n, let_go="Nothing."):
    return ("---\nalias: jen\n---\n\n## Voice & tone\nHer voice.\n\n## Rules\n\n"
            + "".join(f"### Rule {i}\n**Severity:** suggest\n**Citation:** https://example.com/c/{i}\n\n"
                      for i in range(1, n + 1))
            + f"## What they let go\n{let_go}\n")


def put_persona(home, n, **kw):
    d = home / "jen"
    d.mkdir(parents=True, exist_ok=True)
    (d / "PERSONA.md").write_text(persona_text(n, **kw))


def test_a_persona_up_to_30_rules_stays_inline(tmp_path, home):
    put_persona(home, 30)
    diff = tmp_path / "d.patch"
    diff.write_text("diff\n")
    out = run(tmp_path, home, "batches", "--alias", "jen", "--target", diff, "--work-dir", tmp_path / "wd")
    assert out == {"status": "ok", "inline": True, "rules": 30}
    assert not (tmp_path / "wd").exists()


def test_a_persona_over_30_rules_is_cut_into_reviewer_rules_batches(tmp_path, home):
    put_persona(home, 35, let_go="Import ordering.")
    diff = tmp_path / "d.patch"
    diff.write_text("diff\n")
    out = run(tmp_path, home, "batches", "--alias", "jen", "--target", diff, "--work-dir", tmp_path / "wd")
    assert out["inline"] is False and out["rules"] == 35
    assert [s["batch"] for s in out["seats"]] == ["1/2", "2/2"]
    seen = []
    for s in out["seats"]:
        assert s["persona"] == "pip-agents:reviewer-rules"
        b = vr().parse_brief(s["prompt"])
        assert vr().check_brief(b) == [] and b["ref"] == "jen" and b["target"] == str(diff)
        ids = b["rules"].rsplit("(", 1)[1].rstrip(")").split(",")
        assert 8 <= len(ids) <= 30
        seen += ids
        book_path = b["rules"].split(" ", 1)[0]
        book = Path(book_path).read_text()
        assert all(f"### {i} " in book for i in ids) and "## Allowed exceptions\nImport ordering." in book
        assert (os.stat(book_path).st_mode & 0o777) == 0o600
        ctx = Path(b["context"]).read_text()
        assert "Citation URL" in ctx and "unified diff" in ctx
    assert seen == [f"CLONE-jen-{i:03d}" for i in range(1, 36)]


def test_batches_errors(tmp_path, home):
    diff = tmp_path / "d.patch"
    diff.write_text("d\n")
    assert run(tmp_path, home, "batches", "--alias", "ghost", "--target", diff, "--work-dir", tmp_path / "wd",
               expect=1)["status"] == "error"
    d = home / "jen"
    d.mkdir()
    (d / "PERSONA.md").write_text("---\nalias: jen\n---\n## Voice & tone\nx\n")
    out = run(tmp_path, home, "batches", "--alias", "jen", "--target", diff, "--work-dir", tmp_path / "wd", expect=1)
    assert "no rules" in out["error"]


def review_env(ids, findings, **over):
    env = {"result": "pip-agents/1", "kind": "review", "persona": "reviewer-rules", "ref": "jen", "status": "ok",
           "summary": "s", "checked": ["a.py"], "unchecked": [], "out_of_lens": [], "injection_attempts": [],
           "payload": {"lens": "rules", "findings": findings, "medium": [], "rules_checked": f"{len(ids)}/{len(ids)}",
                       "n_a": []}}
    env.update(over)
    return env


def finding(rid, line=3, **kw):
    f = {"id": rid, "rule": "Use auth-aware axios", "file": "a.py", "line": line, "severity": "important",
         "category": "style", "claim": "c", "evidence": f"a.py:{line} plain axios", "fix": "swap it",
         "citation": "https://example.com/c/1"}
    f.update(kw)
    return f


def test_review_ingest_collects_candidates_across_batches(tmp_path, home):
    put_persona(home, 35)
    diff = tmp_path / "d.patch"
    diff.write_text("d\n")
    seats = run(tmp_path, home, "batches", "--alias", "jen", "--target", diff, "--work-dir", tmp_path / "wd")["seats"]
    out = tmp_path / "cands.json"
    for n, s in enumerate(seats):
        ids = vr().parse_brief(s["prompt"])["rules"].rsplit("(", 1)[1].rstrip(")").split(",")
        msg = write(tmp_path / f"m{n}.md", review_env(ids, [finding(ids[0], line=3 + n)]))
        got = run(tmp_path, home, "review-ingest", "--brief", s["brief"], "--message", msg, "--out", out)
        assert got["status"] == "ok" and got["findings"] == 1
    cands = json.loads(out.read_text())
    assert [c["id"] for c in cands][0] == "CLONE-jen-001" and len(cands) == 2
    assert cands[0]["citation"] == "https://example.com/c/1" and cands[0]["severity"] == "important"
    assert set(cands[0]) >= {"id", "rule", "file", "line", "severity", "claim", "evidence", "fix", "citation", "tier"}


def test_review_ingest_rejects_ids_outside_the_batch(tmp_path, home):
    put_persona(home, 35)
    diff = tmp_path / "d.patch"
    diff.write_text("d\n")
    s = run(tmp_path, home, "batches", "--alias", "jen", "--target", diff, "--work-dir", tmp_path / "wd")["seats"][0]
    ids = vr().parse_brief(s["prompt"])["rules"].rsplit("(", 1)[1].rstrip(")").split(",")
    msg = write(tmp_path / "m.md", review_env(ids, [finding("CLONE-jen-999")]))
    got = run(tmp_path, home, "review-ingest", "--brief", s["brief"], "--message", msg, "--out", tmp_path / "c.json",
              expect=1)
    assert got["status"] == "rejected" and not (tmp_path / "c.json").exists()


def test_snapshot_carries_top_level_counts_for_the_gatekeeper(tmp_path, monkeypatch):
    from unittest.mock import patch
    import scripts.collect as collect_mod
    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)
    comment = {"id": 1, "user": "jen", "path": "f.tsx", "body": "x", "diff_hunk": "@@", "reply_thread": [],
               "html_url": "u", "created_at": "2026-05-01T10:00:00Z"}
    with patch.object(collect_mod, "discover_prs", return_value=[100]), \
         patch.object(collect_mod, "fetch_pr", return_value={
             "pr_meta": {"number": 100, "title": "x", "author": "jane", "merged": True},
             "review_comments": [comment, dict(comment, id=2)],
             "issue_comments": [dict(comment, id=3)], "pr_description": None}):
        snap = collect_mod.run_collect(alias="jen", handles=["jen"], repo="o/r", months=6, paths=[], extensions=[],
                                       since=None)
    saved = json.loads((tmp_path / "jen" / "snapshot.json").read_text())
    assert saved["pr_count"] == 1 and saved["comment_count"] == 3 and saved["error_count"] == 0
    assert snap["pr_count"] == 1
    assert all(isinstance(saved[k], int) for k in ("pr_count", "comment_count", "error_count"))


def test_rulebook_matches_review_panels(tmp_path):
    """review-clone mirrors review-panel's clone rulebook (two plugins cannot share an import path): same ids, same
    batches, same file text."""
    text = persona_text(35, let_go="Import ordering.")
    sys.path.insert(0, str(PLUGIN / "scripts"))
    try:
        import clone_rulebook as mine
    finally:
        sys.path.pop(0)
    mine_rules = mine.clone_rules("jen", text)
    mine_out = {
        "ids": [r.id for r in mine_rules],
        "batches": [mine.render("jen", b, mine.clone_exceptions(text)) for b in mine.plan("jen", mine_rules)],
    }
    code = (
        "import json,sys\n"
        f"sys.path.insert(0, {str(ROOT / 'plugins' / 'review-panel')!r})\n"
        "from scripts import rulebook as rb\n"
        "text = sys.stdin.read()\n"
        "rules = rb.clone_rules('jen', text)\n"
        "print(json.dumps({'ids': [r.id for r in rules], 'batches': [rb.render('jen', b, (), rb.clone_exceptions(text)) "
        "for b in rb.plan('jen', rules)]}))\n"
    )
    p = subprocess.run([sys.executable, "-I", "-c", code], input=text, capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)})
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == mine_out
    assert mine.BATCH_CAP == 30


def test_vendored_planner_is_the_repo_planner():
    assert (PLUGIN / "vendor/pip-agents/scripts/batching.py").read_bytes() == (ROOT / "tools" / "batching.py").read_bytes()


def test_check_collect_refuses_a_null_snapshot_path(tmp_path, home):
    out = collect_brief(tmp_path, home)
    env = envelope(out["prompt"])
    env["payload"]["out"] = None
    got = check(tmp_path, home, out["brief"], write(tmp_path / "m.md", env), expect=1)
    assert got["status"] == "failed" and "no snapshot" in got["stderr_tail"]


def test_private_files_are_tightened_even_when_they_pre_exist(tmp_path, home):
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "brief-collect.txt").write_text("old")
    (wd / "brief-collect.txt").chmod(0o644)
    run(tmp_path, home, "brief-collect", "--alias", "jen", "--handles", "bob", "--repo", "o/r", "--months", "3",
        "--work-dir", wd)
    assert (wd / "brief-collect.txt").stat().st_mode & 0o777 == 0o600
