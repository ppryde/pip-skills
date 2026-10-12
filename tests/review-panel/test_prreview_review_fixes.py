"""Round-1 review fixes: repo-top pathspec for the dirty check, content-derived ids."""
import contextlib
import io
import json
import subprocess

import prfake
from prfake import standard
from scripts import prreview


def _plan(tmp_path, g, items, prefix="[x]"):
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"prefix": prefix, "lead": "l", "items": items}))
    out = tmp_path / "plan.json"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        prreview.main(["plan", "--findings", str(f), "--out", str(out)], runner=g)
    return json.loads(out.read_text())


def test_dirty_check_works_from_a_subdirectory(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    def git(*a):
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b", "-c", "user.name=n", *a],
                       check=True, capture_output=True, env=env)
    git("init", "-q")
    (repo / "src" / "a.py").write_text("one\ntwo\n")
    git("add", ".")
    git("commit", "-q", "-m", "x")
    (repo / "src" / "a.py").write_text("one\nCHANGED\n")
    sub = repo / "src" / "deeper"
    sub.mkdir()
    g = standard()

    def runner(argv, timeout=60):
        if argv[:2] == ["git", "status"]:
            p = subprocess.run(argv, cwd=sub, capture_output=True, text=True, env=env)
            return p.returncode, p.stdout, p.stderr
        return g(argv, timeout)

    plan = _plan(tmp_path, runner, [{"id": "p1", "path": "src/a.py", "line": 2, "body": "b"}])
    assert plan["placed"] == []
    assert plan["unplaced"][0]["reason"] == "working-tree-dirty"


def test_missing_ids_derive_from_content_not_position(tmp_path):
    a = _plan(tmp_path, standard(), [{"path": "src/a.py", "line": 2, "body": "first"}])
    b = _plan(tmp_path, standard(), [{"path": "src/a.py", "line": 2, "body": "second"}])
    c = _plan(tmp_path, standard(), [{"path": "src/a.py", "line": 2, "body": "first"}])
    ida, idb, idc = (p["placed"][0]["id"] for p in (a, b, c))
    assert ida != idb and ida == idc


def test_second_run_with_new_body_and_no_ids_is_not_skipped(tmp_path):
    first = _plan(tmp_path, standard(), [{"path": "src/a.py", "line": 2, "body": "old"}])
    marker = f"x\n\n<!-- prreview:{first['placed'][0]['id']} -->"
    g = standard(comments=[{"path": "src/a.py", "position": 3, "body": marker}])
    plan = _plan(tmp_path, g, [{"path": "src/a.py", "line": 2, "body": "old"},
                               {"path": "src/a.py", "line": 2, "body": "new"}])
    assert len(plan["placed"]) == 1 and len(plan["skipped"]) == 1
