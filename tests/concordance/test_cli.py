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
