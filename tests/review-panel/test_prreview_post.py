import contextlib
import io
import json
import subprocess

import pytest

import prfake
from prfake import HEAD, standard
from scripts import prreview

HOSTILE = "``$(touch x) `id` ; rm -rf ~ \"'`` and ```"


@pytest.fixture(autouse=True)
def _no_real_gh(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test reached the real subprocess/gh")
    monkeypatch.setattr(subprocess, "run", boom)


def make(tmp_path, g, items=None):
    items = items or [{"id": "f1", "path": "src/a.py", "line": 2, "body": HOSTILE},
                      {"id": "f2", "path": "src/a.py", "line": None, "body": "general"}]
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"prefix": "[rp]", "lead": "lead", "items": items}))
    out = tmp_path / "plan.json"
    with contextlib.redirect_stdout(io.StringIO()):
        assert prreview.main(["plan", "--findings", str(f), "--out", str(out)], runner=g) == 0
    return out


def post(plan, g, confirmed=True):
    buf = io.StringIO()
    argv = ["post", "--plan", str(plan)] + (["--confirmed"] if confirmed else [])
    with contextlib.redirect_stdout(buf):
        code = prreview.main(argv, runner=g)
    return code, json.loads(buf.getvalue())


def posts(g):
    return [c for c in g.calls if "-X" in c and "POST" in c]


def test_refuses_without_confirmed(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    code, res = post(plan, g, confirmed=False)
    assert code == 2 and not posts(g)


def test_success(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    code, res = post(plan, g)
    assert code == 0 and res == {"status": "posted", "url": "https://github.com/own/rep/pull/7#r1",
                                 "inline": 1, "summary": 1}
    assert len(posts(g)) == 1


def test_stale_head_posts_nothing(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    g.on("gh pr view", prfake.pr_view("f" * 40))
    code, res = post(plan, g)
    assert code == 3 and res["status"] == "stale" and not posts(g)


def test_any_422_gets_exactly_one_summary_only_retry_with_every_finding(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    sent = []

    def post_fn(argv):
        sent.append(json.load(open(argv[argv.index("--input") + 1])))
        return (1, "", "gh: Unprocessable Entity (HTTP 422)") if len(sent) == 1 else (
            0, json.dumps({"html_url": "u"}), "")
    g.on("-X POST", post_fn)
    code, res = post(plan, g)
    assert code == 0 and res["status"] == "fallback_summary"
    assert len(sent) == 2 and sent[1]["comments"] == []
    assert "f1" in sent[1]["body"] and "f2" in sent[1]["body"]
    assert HOSTILE in sent[0]["comments"][0]["body"] or "touch x" in sent[0]["comments"][0]["body"]


def test_second_422_fails_with_text_verbatim(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    g.on("-X POST", (1, "", "gh: Validation Failed (HTTP 422) weird thing"))
    code, res = post(plan, g)
    assert code == 1 and res["status"] == "failed" and "weird thing" in res["error"]
    assert len(posts(g)) == 2


def test_pending_review_is_not_retried(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    g.on("-X POST", (1, "", "gh: Unprocessable Entity (HTTP 422) user_id can only have one pending review per pull request"))
    code, res = post(plan, g)
    assert code == 1 and "pending" in res["error"] and len(posts(g)) == 1


@pytest.mark.parametrize("http", [403, 404, 429, 401])
def test_fatal_codes_never_retried(tmp_path, http):
    g = standard()
    plan = make(tmp_path, g)
    g.on("-X POST", (1, "", f"gh: error (HTTP {http})"))
    code, res = post(plan, g)
    assert code == 1 and res["status"] == "failed" and len(posts(g)) == 1


def test_5xx_with_marker_present_posts_without_second_post(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    run_id = json.loads(plan.read_text())["run_id"]
    g.on("-X POST", (1, "", "gh: Bad Gateway (HTTP 502)"))
    g.on("/pulls/7/reviews?", prfake.pages({"body": f"x <!-- prreview-run:{run_id} -->", "html_url": "U"}))
    code, res = post(plan, g)
    assert code == 0 and res["status"] == "posted" and res["url"] == "U" and len(posts(g)) == 1


def test_5xx_without_marker_retries_once_then_fails(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    g.on("-X POST", (124, "", "timeout"))
    code, res = post(plan, g)
    assert code == 1 and res["status"] == "failed" and len(posts(g)) == 2


def test_5xx_then_success_on_retry(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    g.on("-X POST", [(1, "", "HTTP 500"), (0, json.dumps({"html_url": "ok"}), "")])
    code, res = post(plan, g)
    assert code == 0 and res["url"] == "ok" and len(posts(g)) == 2


def test_shell_safety_roundtrip_and_argv(tmp_path):
    g = standard()
    plan = make(tmp_path, g)
    payload = json.loads(open(json.loads(plan.read_text())["payload_file"]).read())
    assert "touch x" in payload["comments"][0]["body"]  # text round-trips byte-exact in the file
    post(plan, g)
    for argv in g.calls:
        assert isinstance(argv, list)
        assert not any("touch x" in a or "rm -rf" in a for a in argv)


def test_runner_never_uses_a_shell():
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "ok", "")
    import shutil
    orig_run, orig_which = subprocess.run, shutil.which
    subprocess.run, shutil.which = fake_run, lambda n: "/bin/" + n
    try:
        prreview.default_runner(["gh", "api", "x; y"])
    finally:
        subprocess.run, shutil.which = orig_run, orig_which
    assert seen["shell"] is False and seen["argv"] == ["/bin/gh", "api", "x; y"]


def test_classify_branches():
    c = prreview.classify
    assert c(0, "", "") == "ok"
    assert c(1, "", "gh: x (HTTP 422)") == "unprocessable"
    assert c(1, "", "(HTTP 422) one pending review") == "pending"
    assert c(1, "", "(HTTP 403)") == "fatal"
    assert c(1, "", "(HTTP 502)") == "ambiguous"
    assert c(1, "", "") == "ambiguous"
    assert c(124, "", "timeout") == "ambiguous"
