import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts import usage

CLI = Path(__file__).resolve().parents[2] / "plugins" / "concordance" / "scripts" / "cli.py"

BASE = {
    "app/svc.py": "def refund(loan, amount, *, partial=False):\n    return amount\n\n\n"
                  "def unused():\n    return 1\n",
    "app/api.py": "from app.svc import refund\n\n\ndef handle(loan):\n"
                  "    return refund(loan, 5, partial=True)\n",
    "tests/test_api.py": "from app.api import handle\n\n\ndef test_handle():\n    handle(None)\n",
}


def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_review_context_and_check_flag_a_stale_keyword(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    out = cli(repo.root, "review-context")
    assert out.returncode == 0, out.stderr
    assert "base merge-base with main" in out.stdout
    assert "[BR-002] app/api.py:5" in out.stdout
    assert "still passes removed keyword `partial`" in out.stdout
    assert "coverage: 3/3 files indexed" in out.stdout
    check = cli(repo.root, "check")
    assert check.returncode == 1 and "BR-002" in check.stdout


def test_pure_refactor_is_clean(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount, *, partial=False):\n"
                              "    \"\"\"Refund an amount.\"\"\"\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    check = cli(repo.root, "check")
    assert check.returncode == 0 and "check: clean" in check.stdout


def test_worktrees_do_not_leak_into_each_other(make_repo) -> None:
    repo = make_repo(BASE)
    a = repo.worktree("wt-a", "feat-a")
    b = repo.worktree("wt-b", "feat-b")
    a.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n"})
    out_a = cli(a.root, "check", "--base", "main")
    out_b = cli(b.root, "check", "--base", "main")
    assert out_a.returncode == 1 and out_b.returncode == 0
    assert str(b.root) not in out_a.stdout and str(a.root) not in out_b.stdout
    assert "app/api.py" in out_a.stdout


def test_subdirectory_cwd_prints_root_relative_paths(make_repo) -> None:
    repo = make_repo(BASE)
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n"})
    out = cli(repo.root / "app", "removed", "--base", "HEAD")
    assert out.returncode == 0, out.stderr
    assert "app/api.py:5" in out.stdout


def test_callers_and_did_you_mean(make_repo) -> None:
    repo = make_repo(BASE)
    out = cli(repo.root, "callers", "refund")
    assert out.returncode == 0 and "app/api.py:5" in out.stdout and "app.api.handle" in out.stdout
    miss = cli(repo.root, "callers", "refnud")
    assert miss.returncode == 0 and "did you mean" in miss.stdout
    assert "app.svc.refund" in miss.stdout
    tests = cli(repo.root, "tests", "app.svc.refund")
    assert "tests.test_api.test_handle" in tests.stdout and "2 hops" in tests.stdout


def test_no_default_branch_exits_2_with_hint(make_repo) -> None:  # Review Focus 1
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "trunk")
    repo.git("branch", "-q", "-D", "main")
    out = cli(repo.root, "check")
    assert out.returncode == 2 and "--base" in out.stderr and "Traceback" not in out.stderr


def test_check_names_files_it_could_not_parse(make_repo) -> None:  # Review Focus 2
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/broken.py": "def (:\n"})
    out = cli(repo.root, "check")
    assert out.returncode == 0 and "check: clean" in out.stdout
    assert "failed to parse: app/broken.py" in out.stdout


def test_outside_a_repo_exits_2(tmp_path: Path) -> None:
    out = cli(tmp_path, "check")
    assert out.returncode == 2 and "Traceback" not in out.stderr


def test_queries_are_recorded_as_events(make_repo) -> None:
    repo = make_repo(BASE)
    cli(repo.root, "callers", "refund")
    rows = sqlite3.connect(usage.usage_path()).execute("SELECT command FROM events").fetchall()
    assert rows == [("callers",)]


def test_review_context_logs_budget_cuts_and_diff_size(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount + 1\n"})
    assert cli(repo.root, "touched").returncode == 0
    out = cli(repo.root, "review-context", "--budget", "40")
    assert out.returncode == 0, out.stderr
    rows = sqlite3.connect(usage.usage_path()).execute(
        "SELECT command, payload FROM events ORDER BY ts").fetchall()
    assert [c for c, _ in rows] == ["touched", "review-context"]
    logged = json.loads(rows[-1][1])
    assert logged["budget"] == 40 and logged["files"] == 3 and logged["touched"] >= 1
    assert "verdicts" in logged
    assert logged["cut"] or logged["omitted"]


def test_removed_guards_render_as_one_row_not_one_per_test(make_repo) -> None:
    guarded = ("def f(x):\n"
               + "".join(f"    if x == {i}:\n        raise ValueError('b{i}')\n" for i in range(3))
               + "    return x\n")
    tests = "from app import f\n\n\n" + "".join(f"def test_{i}():\n    f({i})\n\n\n"
                                                 for i in range(5))
    repo = make_repo({"app.py": guarded, "tests/test_f.py": tests})
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app.py": "def f(x):\n    return x\n"})
    out = cli(repo.root, "removed")
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("[removed guards] app.f") == 1
    assert "## Removed contract (1)" in out.stdout
    assert "+2 more site(s) (exact)" in out.stdout  # 5 tests, top 3 shown, exact total


def _repo_with_bad_path(make_repo):
    repo = make_repo({"ok.py": "x = 1\n"})
    blob = repo.git("hash-object", "-w", "ok.py").strip()
    subprocess.run(["git", "-C", str(repo.root), "update-index", "--add", "--index-info"],
                   input=f"100644 {blob}\tapp/bad\xff.py\n".encode("latin-1"), check=True)
    return repo


def test_footer_and_check_list_a_non_utf8_path_and_still_exit_zero(make_repo) -> None:
    repo = _repo_with_bad_path(make_repo)
    ctx = cli(repo.root, "review-context")
    assert ctx.returncode == 0, ctx.stderr
    assert "not indexed (non-UTF-8 path)" in ctx.stdout and "bad\\xff.py" in ctx.stdout
    check = cli(repo.root, "check")
    assert check.returncode == 0
    assert "check: clean" in check.stdout
    assert "not indexed (non-UTF-8 path), head view: app/bad\\xff.py" in check.stdout


def test_footer_lists_an_unreadable_dirty_file(make_repo) -> None:
    import os
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
    repo.write({"a.py": "x = 2\n"})
    (repo.root / "a.py").chmod(0)
    try:
        if os.access(repo.root / "a.py", os.R_OK):
            return  # running as a user that ignores permissions (root): nothing to prove
        out = cli(repo.root, "check")
    finally:
        (repo.root / "a.py").chmod(0o644)
    assert out.returncode == 0, out.stderr
    assert "not indexed (unreadable), head view: a.py" in out.stdout


def _drifted(make_repo):
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    return repo


def test_sig_drift_reports_the_verdict_and_exits_zero(make_repo) -> None:
    out = cli(_drifted(make_repo).root, "sig-drift")
    assert out.returncode == 0, out.stderr  # only `check` turns verdicts into exit 1
    assert "[BR-002] app/api.py:5" in out.stdout
    assert "app.svc.refund: unknown keyword(s): partial" in out.stdout
    assert "coverage: 3/3 files indexed" in out.stdout


def test_sig_drift_is_quiet_on_a_pure_refactor(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount, *, partial=False):\n"
                              "    \"\"\"Refund.\"\"\"\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    out = cli(repo.root, "sig-drift")
    assert out.returncode == 0 and "BR-002" not in out.stdout


def test_sig_drift_outside_a_repo_exits_2(tmp_path: Path) -> None:
    out = cli(tmp_path, "sig-drift")
    assert out.returncode == 2 and "concordance:" in out.stderr and "Traceback" not in out.stderr


def test_literals_lists_changed_literals_and_removed_comments(make_repo) -> None:
    repo = make_repo({"app/c.py": "RATE = 'old-rate'\n\n\ndef f():\n    # keep me\n    return RATE\n"})
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/c.py": "RATE = 'new-rate'\n\n\ndef f():\n    return RATE\n"})
    out = cli(repo.root, "literals")
    assert out.returncode == 0, out.stderr
    assert "## Changed literals" in out.stdout and "'new-rate'" in out.stdout
    assert "## Removed comments" in out.stdout and "keep me" in out.stdout


def test_literals_on_an_untouched_tree_is_clean(make_repo) -> None:
    repo = make_repo(BASE)
    out = cli(repo.root, "literals", "--base", "HEAD")
    assert out.returncode == 0 and "Changed literals" not in out.stdout


def test_literals_with_a_bad_base_exits_2(make_repo) -> None:
    out = cli(make_repo(BASE).root, "literals", "--base", "no-such-ref")
    assert out.returncode == 2 and "Traceback" not in out.stderr


def test_index_prints_a_summary_and_is_incremental(make_repo) -> None:
    repo = make_repo(BASE)
    first = cli(repo.root, "index", "--base", "HEAD")
    assert first.returncode == 0, first.stderr
    assert "3 files, 3 parsed, 0 reused, 0 failed, 0 skipped" in first.stdout
    second = cli(repo.root, "index", "--base", "HEAD")
    assert second.returncode == 0 and "0 parsed, 3 reused" in second.stdout


def test_index_names_a_failed_file_and_still_exits_zero(make_repo) -> None:
    repo = make_repo(BASE)
    repo.write({"app/broken.py": "def (:\n"})
    out = cli(repo.root, "index", "--base", "HEAD")
    assert out.returncode == 0 and "1 failed" in out.stdout
    assert "failed to parse: app/broken.py" in out.stdout


def test_index_outside_a_repo_exits_2(tmp_path: Path) -> None:
    out = cli(tmp_path, "index")
    assert out.returncode == 2 and "Traceback" not in out.stderr


def test_setup_ts_without_npm_exits_2(monkeypatch, capsys) -> None:
    from scripts import cli as cli_mod
    from scripts import extract_ts
    monkeypatch.setattr(extract_ts.shutil, "which", lambda _name: None)
    assert cli_mod.main(["setup-ts"]) == 2
    assert "npm not found" in capsys.readouterr().err


def test_setup_ts_runs_a_pinned_npm_ci_and_returns_its_code(monkeypatch) -> None:
    from scripts import cli as cli_mod
    from scripts import extract_ts
    calls: list[tuple[list[str], object]] = []

    def fake_run(cmd, cwd=None, check=None):
        calls.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, 7)

    monkeypatch.setattr(extract_ts.shutil, "which", lambda _name: "/usr/bin/npm")
    monkeypatch.setattr(extract_ts.subprocess, "run", fake_run)
    assert cli_mod.main(["setup-ts"]) == 7  # npm's own exit code passes through
    cmd, cwd = calls[0]
    assert cmd[:2] == ["npm", "ci"] and "--ignore-scripts" in cmd
    assert cwd == extract_ts.NODE_DIR
