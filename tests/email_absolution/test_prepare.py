"""`rules.py prepare` (WF-270 PR C): the batch files and scan output the lead writes for `pip-agents:reviewer-rules`.

The reviewer agents hold no Bash, so the lead runs the script once and hands them files. Nothing here touches
a real tree: scratch repos and out-dirs live in tmp_path."""
import importlib.util
import re
import subprocess
import sys

import pytest

from conftest import PLUGIN, ROOT, SCRIPTS

CFG = dict(email_type="marketing", esp="", templating="html", targets=())
AUDIT = (PLUGIN / "references" / "audit.md").read_text(encoding="utf-8")


def git(repo, *args):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "HOME": str(repo),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "a.html").write_text("<p>one</p>\n<img src=\"a.png\">\n")
    (root / "b.html").write_text("<p>two</p>\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    monkeypatch.chdir(root)
    return root


def prepare(R, docs, files, out, **kw):
    return R.render_prepare(docs, R.Config(**{**CFG, **kw}), files, out)


def parse(text):
    batches = [ln.split(" | ") for ln in text.splitlines() if ln.startswith("batch ")]
    return batches


def test_one_line_per_batch_with_both_paths_and_every_id(R, docs, repo, tmp_path):
    out = tmp_path / "scratch"
    text = prepare(R, docs, ["a.html", "b.html"], out)
    active, _, _ = R.select_rules(docs, R.Config(**CFG))
    expected = R.make_batches(active)
    rows = parse(text)
    assert len(rows) == len(expected) and text.startswith("# prepare: ")
    for n, (row, (names, rules)) in enumerate(zip(rows, expected), 1):
        assert row[0] == f"batch {n}" and row[1] == "+".join(names) and int(row[2]) == len(rules)
        md = out / f"batch-{n}.md"
        assert row[3] == f"{md} L1-{len(md.read_text().splitlines())}", "the span is the whole file, ready for a `rules:` line"
        assert row[5] == ",".join(r.id for r in rules)
        assert row[4] == "-" or row[4] == str(out / f"batch-{n}.scan.txt")


def test_batch_file_starts_on_a_heading_and_carries_each_rule_once(R, docs, repo, tmp_path):
    out = tmp_path / "scratch"
    text = prepare(R, docs, ["a.html"], out)
    for n, row in enumerate(parse(text), 1):
        body = (out / f"batch-{n}.md").read_text(encoding="utf-8")
        assert body.startswith(f"# Batch {n}: ")
        heads = re.findall(r"^### ([A-Z]+-\d{3}) \| (mortal|venial|counsel) \| (regex|contextual|hybrid)", body, re.M)
        assert [h[0] for h in heads] == row[5].split(",")


def test_contextual_rule_carries_statement_and_check(R, docs, repo, tmp_path, by_id):
    out = tmp_path / "scratch"
    text = prepare(R, docs, ["a.html"], out)
    batch = next(n for n, row in enumerate(parse(text), 1) if "UX-016" in row[5].split(","))
    body = (out / f"batch-{batch}.md").read_text(encoding="utf-8")
    section = body.split("### UX-016", 1)[1].split("\n### ", 1)[0]
    assert by_id["UX-016"].statement in section and "check:" in section


def test_scan_file_labels_hits_with_the_scope_path_and_keeps_verify_flags(R, docs, repo, tmp_path):
    out = tmp_path / "scratch"
    text = prepare(R, docs, ["a.html"], out)
    scope = (out / "scope.txt").read_text().splitlines()
    assert scope == [str(repo / "a.html")]
    joined = "".join((out / f"batch-{n}.scan.txt").read_text() for n in range(1, len(parse(text)) + 1)
                     if (out / f"batch-{n}.scan.txt").exists())
    assert f"{repo / 'a.html'}:2 | ACCESS-001 |" in joined
    assert "# scan done:" in joined


def test_symlinks_and_outside_files_are_not_in_scope(R, docs, repo, tmp_path):
    (repo / "link.html").symlink_to(repo / "a.html")
    outside = tmp_path / "outside.html"
    outside.write_text("<p>x</p>\n")
    text = prepare(R, docs, ["a.html", "link.html", str(outside)], tmp_path / "scratch")
    scope = (tmp_path / "scratch" / "scope.txt").read_text().splitlines()
    assert scope == [str(repo / "a.html")]
    assert "skipped: link.html (symlink)" in text and "outside repo" in text


def test_rev_mode_materialises_the_pr_head_and_labels_with_the_copies(R, docs, repo, tmp_path):
    git(repo, "checkout", "-q", "-b", "pr")
    (repo / "a.html").write_text("<p>one</p>\n<img src=\"a.png\">\n<img src=\"b.png\">\n")
    git(repo, "commit", "-qam", "pr")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")  # the work tree is not the PR head
    out = tmp_path / "scratch"
    text = R.render_prepare(docs, R.Config(**CFG), ["a.html"], out, rev=head)
    copy = out / "tree" / "a.html"
    assert copy.read_text().count("<img") == 2, "the copy is the PR head, not the work tree"
    assert (out / "scope.txt").read_text().splitlines() == [str(copy)]
    joined = "".join(p.read_text() for p in out.glob("batch-*.scan.txt"))
    assert f"{copy}:3 | ACCESS-001 |" in joined
    assert "skipped:" not in text


def test_rev_mode_refuses_hostile_paths(R, docs, repo, tmp_path):
    git(repo, "checkout", "-q", "-b", "pr")
    head = git(repo, "rev-parse", "HEAD")
    text = R.render_prepare(docs, R.Config(**CFG), ["../escape.html", "-x"], tmp_path / "scratch", rev=head)
    assert "unsafe path" in text
    assert not (tmp_path / "escape.html").exists() and not (tmp_path / "scratch" / "tree").exists() or \
        not list((tmp_path / "scratch" / "tree").rglob("*.html"))


def test_aliases_are_listed_for_canonical_rules(R, docs, repo, tmp_path):
    text = prepare(R, docs, ["a.html"], tmp_path / "scratch")
    pairs = re.findall(r"^alias: ([A-Z]+-\d{3}) <- ([A-Z0-9,-]+)$", text, re.M)
    assert pairs, "the real doctrines carry aliases"
    canon = {r.id for r in R.all_rules(docs) if not r.is_alias}
    assert all(c in canon for c, _ in pairs)
    every_alias = {r.id for r in R.all_rules(docs) if r.is_alias}
    listed = {a for _, group in pairs for a in group.split(",")}
    assert listed <= every_alias


def test_out_dir_must_be_absolute_and_outside_the_plugin(R, docs, repo, tmp_path):
    with pytest.raises(ValueError):
        prepare(R, docs, ["a.html"], "relative/dir")
    with pytest.raises(ValueError):
        prepare(R, docs, ["a.html"], SCRIPTS.parent / "scratch")


def test_cli_prepare_round_trip(repo, tmp_path):
    out = tmp_path / "cli"
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "prepare", "--out-dir", str(out), "--email-type", "marketing",
                        "--templating", "html", "--files", "a.html"], capture_output=True, text=True, cwd=repo)
    assert r.returncode == 0, r.stderr
    assert parse(r.stdout) and (out / "batch-1.md").is_file() and (out / "scope.txt").is_file()
    bad = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "prepare", "--out-dir", "rel", "--email-type", "marketing",
                          "--files", "a.html"], capture_output=True, text=True, cwd=repo)
    assert bad.returncode == 2 and "absolute" in bad.stderr


def test_doctrine_filter_and_batch_cap_follow_the_one_constant(R, docs, repo, tmp_path):
    spec = importlib.util.spec_from_file_location("pip_batching", ROOT / "tools" / "batching.py")
    b = importlib.util.module_from_spec(spec)
    sys.modules["pip_batching"] = b
    spec.loader.exec_module(b)
    assert (R.BATCH_CAP, R.BATCH_SMALL) == (b.BATCH_CAP, b.BATCH_FLOOR), "drift: rules.py and tools/batching.py"
    text = prepare(R, docs, ["a.html"], tmp_path / "scratch", doctrine="rendering")
    assert all(row[1] == "rendering" for row in parse(text))
    assert all(int(row[2]) <= b.BATCH_CAP for row in parse(text))


def test_plugin_depends_on_pip_agents_and_prepare_is_documented():
    import json
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["dependencies"] == ["pip-agents"] and plugin["version"].startswith("1.7.")
    common = (PLUGIN / "references" / "common.md").read_text(encoding="utf-8")
    assert "`prepare --out-dir D --files <F...>`" in common
    pr_scope = (PLUGIN / "skills" / "visitation" / "references" / "pr-scope.md").read_text(encoding="utf-8")
    assert "prepare --rev" in pr_scope
