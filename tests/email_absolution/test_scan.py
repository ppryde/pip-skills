"""`rules.py scan`: Phase 1 run mechanically, with the safety rules of the WF-266 verdict (change 1).

Line-by-line matching (multiline is opt-in), binary and over-2-MiB files listed as skipped,
a per-file timer on POSIX, and matched lines cut to 200 characters.
"""
import subprocess
import sys

import pytest

from conftest import DOCTRINES, SCRIPTS

CFG = dict(email_type="marketing", esp="", templating="html", targets=())


@pytest.fixture(autouse=True)
def _cwd_is_tmp(tmp_path, monkeypatch):
    """The repo root is the cwd's git toplevel (or the cwd): pin it to tmp_path so scanned tmp files are inside it."""
    monkeypatch.chdir(tmp_path)


def cfg(R, **kw):
    return R.Config(**{**CFG, **kw})


def scan(R, docs, files, **kw):
    return R.render_scan(docs, cfg(R, **kw), [str(f) for f in files])


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_presence_hits_are_file_line_id_matched_line(R, docs, tmp_path):
    f = write(tmp_path, "a.html", "<p>x</p>\n<img src=\"a.png\">\n")
    out = scan(R, docs, [f])
    assert f"{f}:2 | ACCESS-001 | <img src=\"a.png\">" in out
    assert out.rstrip().splitlines()[-1].startswith("# scan done:")


def test_matching_is_line_by_line(R, docs, tmp_path):
    """ACCESS-001 needs an <img> with no alt on ONE line; an alt on the next line does not rescue it."""
    f = write(tmp_path, "a.html", "<img\nalt=\"x\" src=\"a.png\">\n")
    assert "ACCESS-001" not in scan(R, docs, [f])


def test_verify_flag_is_echoed(R, docs, tmp_path):
    f = write(tmp_path, "a.html", "<table>\n")
    out = scan(R, docs, [f])
    line = next(ln for ln in out.splitlines() if "| RENDER-006 |" in ln)
    assert line.endswith("[verify]")
    plain = next(ln for ln in out.splitlines() if "| ACCESS-003 |" in ln)
    assert "[verify]" not in plain


def test_detect_note_that_says_check_marks_the_hit_verify(R, docs, tmp_path):
    # ACCESS-020: regex rule whose note is "check if MSO list margin fix is present ..."
    f = write(tmp_path, "a.html", "<ul>\n<li>x</li>\n</ul>\n")
    out = scan(R, docs, [f], targets=("outlook-2019",))
    line = next(ln for ln in out.splitlines() if "| ACCESS-020 |" in ln)
    assert line.endswith("[verify]")


def test_multiline_rule_matches_across_lines_and_reports_start_line(R, docs, tmp_path):
    """HTML-006 is `multiline`: an anchor wrapped over several lines is still found, at its first line."""
    assert "multiline" in next(r for r in R.all_rules(docs) if r.id == "HTML-006").flags
    f = write(tmp_path, "a.html", "<p>\n<a\n   href=\"https://x.example\">go</a>\n</p>\n")
    out = scan(R, docs, [f])
    assert f"{f}:2 | HTML-006 |" in out
    ok = write(tmp_path, "b.html", "<a\n style=\"color:#000\"\n href=\"https://x.example\">go</a>\n")
    assert "HTML-006" not in scan(R, docs, [ok])


def test_absence_rule_fires_only_when_trigger_present_without_requirement(R, docs, tmp_path):
    """MJML-001: `<mjml` present, `<mj-preview` absent -> one finding at line 1 for the file."""
    f = write(tmp_path, "t.mjml", "<mjml>\n<mj-body></mj-body>\n</mjml>\n")
    out = scan(R, docs, [f], templating="mjml")
    assert f"{f}:1 | MJML-001 | absence:" in out
    ok = write(tmp_path, "ok.mjml", "<mjml>\n<mj-preview>p</mj-preview>\n</mjml>\n")
    assert "| MJML-001 |" not in scan(R, docs, [ok], templating="mjml")
    other = write(tmp_path, "o.html", "<p>no trigger</p>\n")
    assert "| MJML-001 |" not in scan(R, docs, [other], templating="mjml")


def test_matched_line_truncated_to_200_chars(R, docs, tmp_path):
    long = "<img src=\"a.png\" " + "x" * 600 + ">"
    f = write(tmp_path, "a.html", long + "\n")
    line = next(ln for ln in scan(R, docs, [f]).splitlines() if "| ACCESS-001 |" in ln)
    shown = line.split(" | ", 2)[2]
    assert len(shown) <= R.SCAN_LINE_CHARS and shown.endswith("…")


def test_binary_oversized_and_unreadable_files_are_listed_never_silent(R, docs, tmp_path):
    binf = tmp_path / "b.png"
    binf.write_bytes(b"\x89PNG\0\0<img src=x>")
    big = tmp_path / "big.html"
    big.write_bytes(b"<img src=x>\n" * (R.MAX_SCAN_BYTES // 12 + 10))
    out = scan(R, docs, [binf, big, tmp_path / "missing.html"])
    assert f"skipped: {binf} (binary)" in out
    assert f"skipped: {big} (over 2 MiB)" in out
    assert f"skipped: {tmp_path / 'missing.html'} (unreadable" in out
    assert "ACCESS-001" not in out
    assert "# scan done: 0 hit(s), 3 skipped, 0 timed out" in out


def test_per_file_timeout_prints_scan_timed_out_and_continues(R, docs, tmp_path, monkeypatch):
    if not hasattr(__import__("signal"), "setitimer"):
        pytest.skip("no setitimer on this platform")
    evil = R.Rule(id="EVIL-001", prefix="EVIL", doctrine="evil", file=tmp_path, line=1, end=1,
                  transactional="mortal", marketing="mortal",
                  detect=R.Detect("regex", patterns=[r"(a+)+$"]))
    monkeypatch.setattr(R, "select_rules", lambda d, c: ([evil], {}, []))
    monkeypatch.setattr(R, "SCAN_FILE_TIMEOUT_S", 0.3)
    slow = write(tmp_path, "slow.html", "a" * 60 + "b\n")
    fast = write(tmp_path, "fast.html", "ok\n")
    out = R.render_scan(docs, cfg(R), [str(slow), str(fast)])
    assert f"scan timed out: {slow}" in out
    assert "# scan done: 0 hit(s), 0 skipped, 1 timed out" in out


def test_hits_per_rule_are_capped_with_a_summary(R, docs, tmp_path):
    f = write(tmp_path, "a.html", "<img src=\"a.png\">\n" * (R.SCAN_MAX_HITS + 7))
    out = scan(R, docs, [f])
    assert sum(1 for ln in out.splitlines() if "| ACCESS-001 |" in ln and "more matching" not in ln) == R.SCAN_MAX_HITS
    assert "ACCESS-001 | (+7 more matching lines not listed)" in out


def test_scan_follows_select_filters_and_ignores_gen(R, docs, tmp_path):
    f = write(tmp_path, "a.hbs", "{{{subject}}}\n")
    hbs = scan(R, docs, [f], templating="handlebars")
    liq = scan(R, docs, [f], templating="liquid")
    assert "| HBS-002 |" in hbs and "| HBS-002 |" not in liq
    assert "# scan:" in hbs and "regex rules" in hbs


def test_scan_never_emits_aliases_or_template_rules(R, docs, tmp_path):
    f = write(tmp_path, "a.html", "<table><img src=x><a href=\"/rel\">x</a>\n")
    out = scan(R, docs, [f])
    assert not any(f"| {r.id} |" in out for r in R.all_rules(docs) if r.is_alias)
    assert "PREFIX-" not in out


def test_scan_warns_like_select(R, docs, tmp_path):
    f = write(tmp_path, "a.html", "<table>\n")
    assert "warning: unknown rendering_targets outlook" in scan(R, docs, [f], targets=("outlook",))


def test_cli_scan_runs_and_requires_files(tmp_path):
    f = write(tmp_path, "a.html", "<img src=\"a.png\">\n")
    base = [sys.executable, str(SCRIPTS / "rules.py"), "scan", "--email-type", "marketing", "--templating", "html"]
    ok = subprocess.run(base + ["--files", str(f)], capture_output=True, text=True, cwd=tmp_path)
    assert ok.returncode == 0 and "| ACCESS-001 |" in ok.stdout
    missing = subprocess.run(base, capture_output=True, text=True)
    assert missing.returncode == 2


def test_cli_scan_on_unparseable_doctrines_exits_3(tmp_path):
    bad = tmp_path / "doctrines"
    bad.mkdir()
    (bad / "x.md").write_text("no front matter\n**[X-001]** nonsense\n")
    f = write(tmp_path, "a.html", "x\n")
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "--doctrines-dir", str(bad), "scan",
                        "--email-type", "marketing", "--files", str(f)], capture_output=True, text=True)
    assert r.returncode == 3


def test_fire_still_works(tmp_path):
    f = write(tmp_path, "a.html", "<img src=\"a.png\">\n")
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "fire", str(f)], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0 and f"{f}:1 | ACCESS-001" in r.stdout


def test_hostile_long_line_is_bounded_by_the_line_and_the_timer(R, docs, tmp_path):
    """The GOTCHA-004 class: 'rgb(' + spaces. Lint keeps such patterns out; scan must stay bounded anyway."""
    f = write(tmp_path, "h.html", "rgb(" + " " * 20000 + "\n" + "<img src=x>\n")
    out = scan(R, docs, [f])
    assert "# scan done:" in out


# ---- hostile paths (review round 1, B1): a scanned path may come from an untrusted branch

def test_symlinks_are_skipped_never_followed(R, docs, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.html"
    secret.write_text("<img src=x>\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    to_secret = repo / "x.html"
    to_secret.symlink_to(secret)
    zero = repo / "zero.html"
    zero.symlink_to("/dev/zero")
    out = scan(R, docs, [to_secret, zero])
    assert f"skipped: {to_secret} (symlink)" in out
    assert f"skipped: {zero} (symlink)" in out
    assert "ACCESS-001" not in out
    assert "# scan done: 0 hit(s), 2 skipped, 0 timed out" in out


def test_fifo_is_skipped_without_blocking(R, docs, tmp_path):
    import os
    if not hasattr(os, "mkfifo"):
        pytest.skip("no mkfifo")
    fifo = tmp_path / "pipe.html"
    os.mkfifo(fifo)
    out = scan(R, docs, [fifo])
    assert f"skipped: {fifo} (not a regular file)" in out


def test_directory_is_not_a_regular_file(R, docs, tmp_path):
    d = tmp_path / "dir.html"
    d.mkdir()
    assert "(not a regular file)" in scan(R, docs, [d])


def test_a_file_over_the_cap_is_skipped_by_content_not_by_st_size(R, tmp_path, monkeypatch):
    big = tmp_path / "big.html"
    big.write_bytes(b"a" * (R.MAX_SCAN_BYTES + 1))
    real = R.os.lstat

    def lying(p, *a, **k):
        st = real(p, *a, **k)
        return R.os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid, 0,
                                 int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
    monkeypatch.setattr(R.os, "lstat", lying)
    text, why = R.read_scannable(big)
    assert text == "" and why.startswith("over ")


def test_exactly_the_cap_is_still_scanned(R, tmp_path):
    f = tmp_path / "edge.html"
    f.write_bytes(b"a" * R.MAX_SCAN_BYTES)
    text, why = R.read_scannable(f)
    assert why == "" and len(text) == R.MAX_SCAN_BYTES


def test_a_directory_symlink_leaving_the_repo_is_refused_as_outside_repo(R, docs, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.html").write_text("<img src=x>\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "link").symlink_to(outside, target_is_directory=True)
    (repo / "real").mkdir()
    ok = write(repo / "real", "ok.html", "<img src=x>\n")
    monkeypatch.chdir(repo)
    via_link = repo / "link" / "secret.html"
    out = scan(R, docs, [via_link, ok])
    assert f"skipped: {via_link} (outside repo)" in out
    assert "secret.html:1" not in out and f"{ok}:1 | ACCESS-001" in out
    assert ", 1 skipped, 0 timed out" in out
    assert R.read_scannable(via_link) == ("", "outside repo")


def test_a_path_outside_the_repo_is_refused_and_the_git_toplevel_is_the_root(R, tmp_path, monkeypatch):
    import subprocess as sp
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    sp.run(["git", "init", "-q", str(repo)], check=True)
    inner = write(repo / "sub", "a.html", "<img src=x>\n")
    outer = write(tmp_path, "o.html", "<img src=x>\n")
    monkeypatch.chdir(repo / "sub")
    assert R.read_scannable(inner)[1] == ""
    assert R.read_scannable(repo / "sub" / ".." / "sub" / "a.html")[1] == ""
    assert R.read_scannable(outer) == ("", "outside repo")


# ---- savepath (review round 2): the Scribe's confinement, checked by code not prose

def run_savepath(path, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "savepath", str(path)],
                          capture_output=True, text=True, cwd=cwd)


def test_savepath_ok_exists_and_outside(tmp_path):
    repo = tmp_path / "repo"
    (repo / "emails").mkdir(parents=True)
    (repo / "emails" / "old.html").write_text("x")
    ok = run_savepath(repo / "emails" / "new.html", repo)
    assert (ok.stdout.strip(), ok.returncode) == ("ok", 0)
    ex = run_savepath(repo / "emails" / "old.html", repo)
    assert (ex.stdout.strip(), ex.returncode) == ("exists", 3)
    out = run_savepath(tmp_path / "elsewhere.html", repo)
    assert (out.stdout.strip(), out.returncode) == ("outside-repo", 4)
    dots = run_savepath(repo / ".." / "x.html", repo)
    assert (dots.stdout.strip(), dots.returncode) == ("outside-repo", 4)


def test_savepath_refuses_a_symlinked_email_paths_directory_leaving_the_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "emails").symlink_to(outside, target_is_directory=True)
    r = run_savepath(repo / "emails" / "welcome.html", repo)
    assert (r.stdout.strip(), r.returncode) == ("outside-repo", 4)
    (repo / "dangling.html").symlink_to(outside / "nowhere.html")
    d = run_savepath(repo / "dangling.html", repo)
    assert d.returncode in (3, 4)
