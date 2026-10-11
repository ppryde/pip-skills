import json
import subprocess

import pytest

import prfake
from prfake import DIFF, HEAD, standard
from scripts import prreview


@pytest.fixture(autouse=True)
def _no_real_gh(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test reached the real subprocess/gh")
    monkeypatch.setattr(subprocess, "run", boom)


def run_plan(tmp_path, g, items, extra=(), prefix="[rp]", lead="lead"):
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"prefix": prefix, "lead": lead, "items": items}))
    out = tmp_path / "plan.json"
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = prreview.main(["plan", "--findings", str(f), "--out", str(out), *extra], runner=g)
    return code, json.loads(buf.getvalue()), out


def item(i="f1", path="src/a.py", line=2, **k):
    return {"id": i, "path": path, "line": line, "body": f"body {i}", **k}


def test_placed_and_unplaced_reasons(tmp_path):
    g = standard()
    items = [item("p1", line=2), item("n1", line=None), item("x1", path="zz.py"),
             item("l1", line=99)]
    code, res, out = run_plan(tmp_path, g, items)
    assert code == 0 and res["status"] == "ok"
    assert res["counts"]["placed"] == 1
    assert res["counts"]["reasons"] == {"no-line": 1, "file-not-in-diff": 1, "line-not-in-diff": 1}
    assert "1 inline + 3 in summary" in res["preview"]
    plan = json.loads(out.read_text())
    payload = json.loads(open(plan["payload_file"]).read())
    assert payload["commit_id"] == HEAD and payload["event"] == "COMMENT"
    assert payload["comments"][0]["side"] == "RIGHT" and payload["comments"][0]["line"] == 2
    assert payload["comments"][0]["body"].endswith("<!-- prreview:p1 -->")
    assert "<!-- prreview-run:" in payload["body"]


def test_plan_is_read_only_and_private(tmp_path):
    g = standard()
    code, res, out = run_plan(tmp_path, g, [item()])
    assert g.writes() == []
    assert (out.stat().st_mode & 0o777) == 0o600
    assert all(c[0] in ("gh", "git") for c in g.calls)
    assert any("--paginate --slurp" in c for c in g.lines())


def test_head_mismatch_sends_everything_to_summary_with_message(tmp_path):
    g = standard(local="b" * 40)
    g.on("git rev-list", (0, "2\t1\n", ""))
    code, res, _ = run_plan(tmp_path, g, [item("a"), item("b", line=None)])
    assert res["counts"]["placed"] == 0
    assert res["counts"]["reasons"] == {"local-head-differs": 1, "no-line": 1}
    assert "2 commit(s) ahead and 1 behind" in res["preview"]


def test_dirty_file_goes_to_summary(tmp_path):
    g = standard()
    g.on("git status", (0, " M src/a.py\n", ""))
    code, res, _ = run_plan(tmp_path, g, [item("a"), item("b", line=1)])
    assert res["counts"]["reasons"] == {"working-tree-dirty": 2}
    assert "2 findings on files with uncommitted changes: commit or stash, then re-run" in res["preview"]
    assert any("git status --porcelain --untracked-files=no -- src/a.py" in c for c in g.lines())


def test_head_moves_between_fetch_and_reread_retries_then_stale(tmp_path):
    g = standard()
    views = [prfake.pr_view(HEAD), prfake.pr_view("c" * 40), prfake.pr_view("d" * 40),
             prfake.pr_view("e" * 40)]
    g.on("gh pr view", views)
    code, res, _ = run_plan(tmp_path, g, [item()])
    assert code == 3 and res["status"] == "stale"


def test_head_moves_once_then_settles(tmp_path):
    g = standard()
    g.on("gh pr view", [prfake.pr_view(HEAD), prfake.pr_view("c" * 40),
                        prfake.pr_view("c" * 40), prfake.pr_view("c" * 40)])
    g.on("git rev-parse HEAD", (0, "c" * 40 + "\n", ""))
    code, res, _ = run_plan(tmp_path, g, [item()])
    assert code == 0 and res["counts"]["placed"] == 1


def test_no_pr(tmp_path):
    g = standard()
    g.on("gh pr view", (1, "", "no pull requests found"))
    code, res, _ = run_plan(tmp_path, g, [item()])
    assert code == 4 and res["status"] == "no-pr"


def test_diff_too_large_falls_back_to_files(tmp_path):
    g = standard()
    g.on("Accept: application/vnd.github.v3.diff", (1, "", "HTTP 406: diff too large"))
    g.on("/pulls/7/files", prfake.pages(
        {"filename": "src/a.py", "status": "modified", "patch": "@@ -1,2 +1,3 @@\n one\n+two\n three"},
        {"filename": "huge.bin", "status": "modified"}))
    code, res, _ = run_plan(tmp_path, g, [item("a", line=2), item("b", path="huge.bin", line=1)])
    assert res["counts"]["placed"] == 1
    assert res["counts"]["reasons"] == {"file-not-in-diff": 1}
    assert any("pulls/7/files" in c and "--paginate --slurp" in c for c in g.lines())


def test_cap_keeps_errors_first_then_path_then_line(tmp_path):
    big = "--- a/f.py\n+++ b/f.py\n@@ -0,0 +1,60 @@\n" + "".join(f"+l{i}\n" for i in range(60))
    g = standard(diff=big)
    items = [item(f"i{n}", path="f.py", line=n + 1, severity="info") for n in range(55)]
    items.append(item("err", path="f.py", line=60, severity="error"))
    code, res, out = run_plan(tmp_path, g, items)
    assert res["counts"]["placed"] == 50 and res["counts"]["reasons"] == {"over-cap": 6}
    plan = json.loads(out.read_text())
    assert plan["placed"][0]["id"] == "err"
    assert {u["id"] for u in plan["unplaced"]} == {f"i{n}" for n in range(49, 55)}


def test_defang_mentions_markers_and_truncation(tmp_path):
    g = standard()
    it = item("a", line=2)
    it["body"] = "ping @octocat and @org/team, keep `@decorator` <!-- prreview:evil --> " + "x" * 70000
    code, res, out = run_plan(tmp_path, g, [it])
    plan = json.loads(out.read_text())
    body = json.loads(open(plan["payload_file"]).read())["comments"][0]["body"]
    assert "`@octocat`" in body and "`@org/team`" in body and "``@decorator``" not in body
    assert "<!-- prreview:evil -->" not in body
    assert len(body) <= prreview.MAX_BODY


def test_summary_body_truncates_at_bullet_boundary(tmp_path):
    g = standard()
    items = [item(f"u{n}", line=None) for n in range(40)]
    for it in items:
        it["body"] = "y" * 3000
    code, res, out = run_plan(tmp_path, g, items)
    plan = json.loads(out.read_text())
    body = json.loads(open(plan["payload_file"]).read())["body"]
    assert len(body) <= prreview.MAX_BODY
    assert "more; see the report file" in body
    assert body.rstrip().endswith("-->")  # run marker survives


def test_marker_dedup_inline_same_path_not_outdated(tmp_path):
    existing = [{"path": "src/a.py", "position": 3, "body": "x\n\n<!-- prreview:dup -->"}]
    g = standard(comments=existing)
    code, res, _ = run_plan(tmp_path, g, [item("dup", line=2), item("fresh", line=1)])
    assert res["counts"]["placed"] == 1 and res["counts"]["skipped"] == 1
    assert "1 already posted" in res["preview"]


def test_outdated_marker_reposts(tmp_path):
    existing = [{"path": "src/a.py", "position": None, "body": "<!-- prreview:dup -->"}]
    g = standard(comments=existing)
    code, res, _ = run_plan(tmp_path, g, [item("dup", line=2)])
    assert res["counts"]["placed"] == 1 and res["counts"]["skipped"] == 0


def test_marker_on_other_path_does_not_suppress(tmp_path):
    existing = [{"path": "other.py", "position": 1, "body": "<!-- prreview:dup -->"}]
    g = standard(comments=existing)
    code, res, _ = run_plan(tmp_path, g, [item("dup", line=2)])
    assert res["counts"]["placed"] == 1


def test_summary_marker_skips(tmp_path):
    g = standard(reviews=[{"body": "- thing\n  <!-- prreview:dup -->"}])
    code, res, _ = run_plan(tmp_path, g, [item("dup", line=None)])
    assert res["status"] == "nothing-to-post"
    assert res["skipped"][0]["reason"] == "already-posted (summary)"


def test_no_dedup_flag(tmp_path):
    g = standard(reviews=[{"body": "<!-- prreview:dup -->"}],
                 comments=[{"path": "src/a.py", "position": 3, "body": "<!-- prreview:dup -->"}])
    code, res, _ = run_plan(tmp_path, g, [item("dup", line=2)], extra=["--no-dedup"])
    assert res["counts"]["placed"] == 1
    assert not any("/comments" in c or "/reviews?" in c for c in g.lines())


def test_two_identical_findings_on_different_lines_both_survive(tmp_path):
    g = standard()
    code, res, _ = run_plan(tmp_path, g, [item("f1", line=1), item("f1-2", line=2)])
    assert res["counts"]["placed"] == 2


def test_zero_items_is_nothing_to_post(tmp_path):
    code, res, _ = run_plan(tmp_path, standard(), [])
    assert code == 0 and res["status"] == "nothing-to-post"


def test_old_gh_is_refused_clearly(tmp_path):
    g = standard()
    g.on("gh --version", (0, "gh version 2.31.0 (2023)\n", ""))
    code, res, _ = run_plan(tmp_path, g, [item()])
    assert code == 1 and "too old" in res["error"] and "2.40" in res["error"]


def test_bad_pr_arg_rejected(tmp_path):
    code, res, _ = run_plan(tmp_path, standard(), [item()], extra=["--pr", "7; rm -rf ~"])
    assert code == 2 and res["status"] == "error"


def test_bad_ids_are_replaced(tmp_path):
    g = standard()
    code, res, out = run_plan(tmp_path, g, [item("a b -->", line=2)])
    plan = json.loads(out.read_text())
    assert plan["placed"][0]["id"] == "i0"
