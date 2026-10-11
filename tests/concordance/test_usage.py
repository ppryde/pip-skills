import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts import gitio, paths, usage

CLI = Path(__file__).resolve().parents[2] / "plugins" / "concordance" / "scripts" / "cli.py"
DAY = 86400.0


def cli(cwd: Path, *args: str,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, capture_output=True,
                          text=True, env=env, check=False)


def test_usage_log_lives_apart_from_the_index(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    assert usage.usage_path() == tmp_path / "config" / "concordance" / "usage.db"
    assert usage.usage_path().parent != paths.store_path(gitio.common_dir(repo.root)).parent


def test_size_buckets() -> None:
    assert [usage.size_bucket(n) for n in (0, 1, 5, 6, 20, 21)] == \
        ["0", "1-5", "1-5", "6-20", "6-20", "21+"]


def test_report_aggregates_cost_budget_verdicts_and_reviews(tmp_path: Path) -> None:
    db = tmp_path / "u.db"
    now = 1_000 * DAY
    for i, (touched, cut) in enumerate([(2, {}), (3, {"Callers": 4}), (30, {"Callers": 9})]):
        usage.record("review-context", "repo-a", "wt", 100 * (i + 1), 1000 + i, 0,
                     {"budget": 4000, "cut": cut, "omitted": [], "touched": touched,
                      "verdicts": i}, session=f"s{i}", path=db)
    usage.record("check", "repo-b", "wt", 50, 10, 1, {"verdicts": 2}, path=db)
    usage.record("record-review", "repo-a", None, 0, 0, 0,
                 {"findings": 3, "via_index": 2, "steps": {"1": 1, "3": 1}}, path=db)
    usage.record("record-review", "repo-a", None, 0, 0, 0,
                 {"findings": 0, "via_index": 0, "steps": {}}, path=db)
    usage.record("review-context", "repo-a", "wt", 1, 1, 0, {"touched": 1}, path=db)
    con = sqlite3.connect(db)
    con.execute("UPDATE events SET ts=? WHERE latency_ms=1", (now - 40 * DAY,))
    con.execute("UPDATE events SET ts=? WHERE ts>?", (now - DAY, now - 30 * DAY))
    con.commit()
    con.close()

    rep = usage.report(days=30, now=now, path=db)
    runs = rep["commands"]["review-context"]
    assert runs["runs"] == 3 and runs["sessions"] == 3
    assert runs["tokens_p50"] == 1001 and runs["latency_p90"] == 300
    budget = rep["budget"]
    assert budget["review_runs"] == 3 and budget["cut_runs"] == 2
    assert budget["by_size"]["1-5"] == {"runs": 2, "cut": 1}
    assert budget["by_size"]["21+"] == {"runs": 1, "cut": 1}
    assert budget["sections_cut"] == {"Callers": 2}
    assert rep["verdicts"] == {"runs": 4, "runs_with_verdicts": 3, "total": 5}
    assert rep["reviews"] == {"count": 2, "clean": 1, "findings": 3, "via_index": 2,
                              "by_step": {"1": 1, "3": 1}}
    assert usage.report(days=30, repo="repo-b", now=now, path=db)["commands"].keys() == {"check"}


def test_format_report_is_readable_and_handles_an_empty_log(tmp_path: Path) -> None:
    empty = usage.format_report(usage.report(path=tmp_path / "none.db"))
    assert "no concordance usage" in empty
    db = tmp_path / "u.db"
    usage.record("review-context", "repo-a", "wt", 120, 900, 0,
                 {"budget": 4000, "cut": {"Callers": 3}, "touched": 4, "verdicts": 1}, path=db)
    usage.record("record-review", "repo-a", None, 0, 0, 0,
                 {"findings": 2, "via_index": 1, "steps": {"3": 1}}, path=db)
    text = usage.format_report(usage.report(path=db))
    for heading in ("## Usage", "## Budget pressure", "## Effectiveness"):
        assert heading in text
    assert "Callers" in text and "1 of 2 findings via concordance" in text


def test_cli_records_queries_and_failures_but_not_stats(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"app/m.py": "def f():\n    return 1\n"})
    assert cli(repo.root, "callers", "f").returncode == 0
    assert cli(tmp_path, "check").returncode == 2
    assert cli(repo.root, "stats").returncode == 0
    rows = sqlite3.connect(usage.usage_path()).execute(
        "SELECT command, exit_code, payload FROM events ORDER BY ts").fetchall()
    assert [(c, e) for c, e, _ in rows] == [("callers", 0), ("check", 2)]
    assert "error" in json.loads(rows[1][2])


def test_record_review_then_stats_json(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    out = cli(repo.root, "record-review", "--findings", "3", "--via-index", "2",
              "--steps", "1:1,3:1")
    assert out.returncode == 0 and out.stdout.strip() == \
        "recorded review: 3 findings (2 via concordance)"
    rep = json.loads(cli(repo.root, "stats", "--json", "--repo", "this").stdout)
    assert rep["reviews"]["via_index"] == 2 and rep["reviews"]["by_step"] == {"1": 1, "3": 1}


def test_record_review_rejects_impossible_counts(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    bad = cli(repo.root, "record-review", "--findings", "1", "--via-index", "2")
    assert bad.returncode == 2 and "Traceback" not in bad.stderr
    bad_steps = cli(repo.root, "record-review", "--findings", "1", "--via-index", "1",
                    "--steps", "one")
    assert bad_steps.returncode == 2 and "--steps" in bad_steps.stderr


def test_printing_non_ascii_under_an_ascii_stdout_does_not_traceback(make_repo) -> None:
    repo = make_repo({"app/m.py": "def f():\n    return 1\n"})
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    out = cli(repo.root, "callers", "café", env=env)  # the miss message echoes the name
    assert out.returncode == 0 and "Traceback" not in out.stderr
    assert "caf" in out.stdout
