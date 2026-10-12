import json
import subprocess
import sys
from pathlib import Path

from scripts.render import est_tokens

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


def test_callers_json_matches_text_size_and_names_hits(make_repo) -> None:
    repo = make_repo(BASE)
    text = cli(repo.root, "callers", "refund")
    js = cli(repo.root, "callers", "refund", "--json")
    assert js.returncode == 0, js.stderr
    doc = json.loads(js.stdout)
    assert doc["command"] == "callers" and doc["found"] is True
    assert doc["est_tokens"] == est_tokens(text.stdout.rstrip("\n"))
    assert doc["definition"] == "app/svc.py"
    assert {"path": "app/api.py", "line": 5} in doc["hits"]
    assert doc["root"] == str(repo.root.resolve())


def test_callers_json_miss_is_not_found(make_repo) -> None:
    repo = make_repo(BASE)
    doc = json.loads(cli(repo.root, "callers", "nope_nothing", "--json").stdout)
    assert doc["found"] is False and doc["hits"] == []
    assert doc["target"] is None and doc["definition"] is None


def test_check_json_counts_verdicts_and_keeps_exit_code(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    js = cli(repo.root, "check", "--json")
    assert js.returncode == 1
    doc = json.loads(js.stdout)
    assert doc["exit_code"] == 1 and doc["verdicts"] >= 1


def test_review_context_json_lists_sections(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    doc = json.loads(cli(repo.root, "review-context", "--json").stdout)
    assert doc["sections"] and all({"title", "count"} <= set(s) for s in doc["sections"])


def test_tests_json_hits_have_path_and_line(make_repo) -> None:
    repo = make_repo(BASE)
    doc = json.loads(cli(repo.root, "tests", "refund", "--json").stdout)
    assert doc["found"] is True and doc["hits"]
    assert all(set(h) == {"path", "line"} for h in doc["hits"])
    assert any(h["path"] == "tests/test_api.py" for h in doc["hits"])


def test_coverage_json_has_no_target_keys(make_repo) -> None:
    repo = make_repo(BASE)
    doc = json.loads(cli(repo.root, "coverage", "--json").stdout)
    assert doc["command"] == "coverage" and doc["root"]
    assert not {"found", "target", "definition", "hits"} & set(doc)
