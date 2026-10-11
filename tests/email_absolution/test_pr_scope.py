"""WF-266 PR 3: Visitation reads the PR head (VI-1), tells changed lines from existing debt (VI-3)."""
import re
import subprocess

import pytest

from conftest import PLUGIN

CFG = dict(email_type="marketing", esp="", templating="html", targets=())
AUDIT = (PLUGIN / "references" / "audit.md").read_text(encoding="utf-8")
SKILL = (PLUGIN / "skills" / "visitation" / "SKILL.md").read_text(encoding="utf-8")


def git(repo, *args):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "HOME": str(repo),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.html").write_text("<p>one</p>\n<img src=\"a.png\">\n<p>three</p>\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "-q", "-b", "pr")
    (tmp_path / "a.html").write_text("<p>one</p>\n<img src=\"a.png\">\n<p>three</p>\n<img src=\"b.png\">\n")
    git(tmp_path, "commit", "-qam", "pr")
    head = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "-q", "main")  # work tree is NOT the PR head
    monkeypatch.chdir(tmp_path)
    return tmp_path, base, head


def test_parse_hunks(R):
    diff = "@@ -0,0 +1,3 @@\n+a\n@@ -5 +7 @@\n@@ -9,2 +11,0 @@\n@@ -20,0 +30,2 @@\n"
    assert R.parse_hunks(diff) == [(1, 3), (7, 7), (30, 31)]


def test_hunks_lists_added_lines(R, repo):
    _, base, head = repo
    assert R.render_hunks(base, head, ["a.html"]) == "a.html: 4\n"


def test_hunks_unknown_and_refusals(R, repo):
    _, base, head = repo
    assert R.render_hunks(base, head, ["nope.html"]) == "nope.html: unknown\n"
    assert R.render_hunks(base, head, ["../x.html"]) == "../x.html: unknown\n"
    assert R.render_hunks("--output=x", head, ["a.html"]).startswith("error:")
    assert R.render_hunks(base, "HEAD", ["a.html"]).startswith("error:")


def test_scan_rev_reads_the_pr_head_not_the_work_tree(R, docs, repo):
    _, base, head = repo
    cfg = R.Config(**CFG)
    wt = R.render_scan(docs, cfg, ["a.html"])
    pr = R.render_scan(docs, cfg, ["a.html"], head)
    assert "a.html:4 | ACCESS-001" not in wt        # main checked out: 3 lines
    assert "a.html:4 | ACCESS-001" in pr
    assert "a.html:2 | ACCESS-001" in pr


def test_scan_rev_refuses_hostile_input(R, docs, repo):
    _, base, head = repo
    cfg = R.Config(**CFG)
    for rev, path, why in [("HEAD", "a.html", "bad revision"), (head, "-x", "unsafe path"),
                           (head, "../a.html", "unsafe path"), (head, "missing.html", "not in that commit")]:
        out = R.render_scan(docs, cfg, [path], rev)
        assert f"skipped: {path} ({why}" in out, out


def test_scan_rev_skips_symlink_blobs(R, docs, repo):
    d, base, _ = repo
    git(d, "checkout", "-q", "-b", "sym")
    (d / "l.html").symlink_to("/etc/passwd")
    git(d, "add", ".")
    git(d, "commit", "-qm", "sym")
    sha = git(d, "rev-parse", "HEAD")
    out = R.render_scan(docs, R.Config(**CFG), ["l.html"], sha)
    assert "skipped: l.html (symlink" in out


def test_cli_hunks_and_scan_rev(repo):
    from conftest import SCRIPTS
    import sys
    _, base, head = repo
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "hunks", "--base", base, "--rev", head,
                        "--files", "a.html"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "a.html: 4\n"
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "scan", "--email-type", "marketing",
                        "--templating", "html", "--rev", head, "--files", "a.html"], capture_output=True, text=True)
    assert r.returncode == 0 and "a.html:4 | ACCESS-001" in r.stdout


# ---- policy text (VI-1 / VI-3)

def test_pr_mode_reads_the_head_commit():
    assert "gh pr view '<number>' --json headRefOid,baseRefName,files" in AUDIT
    assert "DELETED" in AUDIT and "git fetch origin 'pull/<number>/head'" in AUDIT
    assert "git show '<oid>:<path>'" in AUDIT and "scan --rev '<oid>'" in AUDIT
    assert "gh pr diff" not in AUDIT


def test_preexisting_policy_is_stated_in_audit_and_skill():
    assert "(pre-existing)" in AUDIT and "existing debt" in AUDIT
    assert "blocks" in SKILL and "(pre-existing)" in SKILL
    assert "does not block the change" not in SKILL
    sample = (PLUGIN / "skills" / "visitation" / "references" / "verdict-sample.md").read_text(encoding="utf-8")
    assert "(pre-existing)" in sample and "EXISTING DEBT" in sample
    for rid in set(re.findall(r"\[([A-Z]+-\d{3})\]", sample)):
        assert rid in (PLUGIN / "doctrines" / "INDEX.md").read_text(encoding="utf-8")


def test_html004_is_venial_on_both_tracks(docs):
    r = {x.id: x for d in docs for x in d.rules}["HTML-004"]
    assert (r.transactional, r.marketing) == ("venial", "venial")
