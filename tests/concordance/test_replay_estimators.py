from pathlib import Path

from scripts.replay import drift, estimators, runner
from scripts.replay.transcript import ToolCall

from .test_cli import BASE


def _call(name: str, inp: dict, result: str, cwd: Path, seq: int = 0) -> ToolCall:
    return ToolCall(f"t{seq}", "", name, inp, result, str(cwd), seq)


def test_bare_identifier_grep_matches_callers(tmp_path: Path) -> None:
    q = estimators.match(_call("Grep", {"pattern": "refund"}, "", tmp_path))
    assert q == estimators.Query("callers", "grep", ["callers", "refund"])


def test_regex_pattern_is_not_a_symbol(tmp_path: Path) -> None:
    for pat in ("foo.*\\(", "refund; rm -rf /", "a b", ""):
        assert estimators.match(_call("Grep", {"pattern": pat}, "", tmp_path)) is None


def test_callers_answerable_yes_when_reads_stay_in_callers(make_repo) -> None:
    repo = make_repo(BASE)
    grep = _call("Grep", {"pattern": "refund"},
                 f"Found 2 files\n{repo.root}/app/api.py\n{repo.root}/app/svc.py", repo.root, 0)
    later = [_call("Read", {"file_path": f"{repo.root}/app/api.py"}, "x", repo.root, 1)]
    q = estimators.match(grep)
    assert q is not None
    est = estimators.estimate(q, grep, later)
    assert est.covered and est.concordance_tokens > 0 and est.answerable == "yes"


def test_callers_answerable_no_when_agent_reads_a_non_caller_hit(make_repo) -> None:
    repo = make_repo({**BASE, "docs/notes.py": "# refund is documented here\n"})
    grep = _call("Grep", {"pattern": "refund"},
                 f"{repo.root}/docs/notes.py:1:# refund is documented here", repo.root, 0)
    later = [_call("Read", {"file_path": f"{repo.root}/docs/notes.py"}, "x", repo.root, 1)]
    q = estimators.match(grep)
    assert q is not None
    assert estimators.estimate(q, grep, later).answerable == "no"


def test_callers_answerable_unknown_when_nothing_is_read_after(make_repo) -> None:
    repo = make_repo(BASE)
    grep = _call("Grep", {"pattern": "refund"}, f"{repo.root}/app/api.py", repo.root, 0)
    q = estimators.match(grep)
    assert q is not None
    assert estimators.estimate(q, grep, []).answerable == "unknown"


def test_missing_cwd_is_not_covered(tmp_path: Path) -> None:
    grep = _call("Grep", {"pattern": "refund"}, "", tmp_path / "gone", 0)
    q = estimators.match(grep)
    assert q is not None
    est = estimators.estimate(q, grep, [])
    assert not est.covered and est.answerable == "unknown"


def test_unknown_symbol_is_not_covered(make_repo) -> None:
    repo = make_repo(BASE)
    grep = _call("Grep", {"pattern": "nosuchsymbol"}, "", repo.root, 0)
    q = estimators.match(grep)
    assert q is not None
    assert not estimators.estimate(q, grep, []).covered


def test_passthrough_counts_the_agents_own_concordance_call(tmp_path: Path) -> None:
    call = _call("Bash", {"command": "python x/concordance/scripts/cli.py review-context"},
                 "## Touched (3)\n" * 10, tmp_path)
    q = estimators.match(call)
    assert q is not None and q.estimator == "passthrough"
    est = estimators.estimate(q, call, [])
    assert est.covered and est.concordance_tokens > 0


def test_runner_reports_latency_and_never_uses_a_shell(make_repo) -> None:
    repo = make_repo(BASE)
    ans = runner.run(["callers", "refund"], str(repo.root))
    assert ans.ok and ans.exit_code == 0 and ans.latency_ms > 0 and ans.doc["found"] is True


def test_runner_treats_empty_stdout_exit_2_as_failed(tmp_path: Path) -> None:
    ans = runner.run(["callers", "refund"], str(tmp_path))  # not a git repo: exit 2, no stdout
    assert not ans.ok and ans.doc == {}


def test_drift_detects_a_changed_file(make_repo) -> None:
    repo = make_repo(BASE)
    seen = "".join(f"{i:>6}\t{line}\n" for i, line in
                   enumerate(BASE["app/api.py"].splitlines(), 1))
    read = _call("Read", {"file_path": str(repo.root / "app/api.py")}, seen, repo.root, 0)
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "no"
    repo.write({"app/api.py": "changed = 1\n"})
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "yes"
    assert drift.drifted([], str(repo.root / "app/api.py"), str(repo.root)) == "unknown"


def test_partial_read_cannot_tell(tmp_path: Path) -> None:
    read = _call("Read", {"file_path": "a.py", "limit": 5}, "     1\tx\n", tmp_path)
    assert drift.full_read_blob(read) is None
    assert drift.drifted([read], "a.py", str(tmp_path)) == "unknown"
