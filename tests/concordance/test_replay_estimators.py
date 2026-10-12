from pathlib import Path

from scripts.replay import drift, estimators, runner
from scripts.replay.transcript import ToolCall

from .test_cli import BASE


def _call(name: str, inp: dict, result: str, cwd: Path, seq: int = 0) -> ToolCall:
    return ToolCall(f"t{seq}", "", name, inp, result, str(cwd), seq)


def _read_text(content: str) -> str:
    # real Read output: "N\t<line>" joined by "\n", never ending in one; a file's trailing
    # newline shows up as an empty final numbered line
    return "\n".join(f"{i}\t{line}" for i, line in enumerate(content.split("\n"), 1))


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
    seen = _read_text(BASE["app/api.py"])
    read = _call("Read", {"file_path": str(repo.root / "app/api.py")}, seen, repo.root, 0)
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "no"
    repo.write({"app/api.py": "changed = 1\n"})
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "yes"
    assert drift.drifted([], str(repo.root / "app/api.py"), str(repo.root)) == "unknown"


def test_partial_read_cannot_tell(tmp_path: Path) -> None:
    read = _call("Read", {"file_path": "a.py", "limit": 5}, "     1\tx\n", tmp_path)
    assert drift.full_read_blob(read) is None
    assert drift.drifted([read], "a.py", str(tmp_path)) == "unknown"


def test_grep_with_narrowing_options_is_not_covered(make_repo) -> None:
    repo = make_repo(BASE)
    (repo.root / "other").mkdir()
    for extra in ({"glob": "*.py"}, {"type": "py"}, {"multiline": True}, {"-i": True},
                  {"path": "app"}, {"path": str(repo.root / "app")},
                  {"path": str(repo.root.parent)}):
        call = _call("Grep", {"pattern": "refund", **extra}, "", repo.root)
        assert estimators.match(call) is None, extra


def test_grep_with_path_at_cwd_or_root_is_still_covered(make_repo) -> None:
    repo = make_repo(BASE)
    for path in (str(repo.root), "."):
        call = _call("Grep", {"pattern": "refund", "path": path}, "", repo.root)
        assert estimators.match(call) is not None, path
    sub = repo.root / "app"
    call = _call("Grep", {"pattern": "refund", "path": str(repo.root)}, "", sub)
    assert estimators.match(call) is not None


def test_bad_est_tokens_is_not_covered(monkeypatch) -> None:
    for bad in (None, "5", True, 1.5):
        monkeypatch.setattr(estimators.runner, "run", lambda *a, _b=bad, **k: runner.Answer(
            True, {"found": True, "est_tokens": _b, "root": "/"}, 3, 0))
        call = _call("Grep", {"pattern": "x"}, "", Path("/"))
        q = estimators.match(call)
        assert q is not None
        assert not estimators.estimate(q, call, []).covered, bad


def test_relative_grep_paths_resolve_against_the_grep_cwd(make_repo) -> None:
    repo = make_repo(BASE)
    sub = repo.root / "app"
    grep = _call("Grep", {"pattern": "refund"}, "api.py:5:    return refund", sub, 0)
    later = [_call("Read", {"file_path": "api.py"}, "x", sub, 1)]
    q = estimators.match(grep)
    assert q is not None
    assert estimators.estimate(q, grep, later).answerable == "yes"


def test_runner_timeout_fails_without_hanging(make_repo) -> None:
    repo = make_repo(BASE)
    ans = runner.run(["callers", "refund"], str(repo.root), timeout=0.001)
    assert not ans.ok and ans.doc == {}


def test_drift_roundtrips_crlf_and_odd_separators(make_repo) -> None:
    content = "a = 1\r\nb = '\x0c \u2028'\r\n"
    repo = make_repo({"f.py": "x\n"})
    (repo.root / "f.py").write_bytes(content.encode())
    read = _call("Read", {"file_path": str(repo.root / "f.py")}, _read_text(content), repo.root)
    assert drift.drifted([read], str(repo.root / "f.py"), str(repo.root)) == "no"


def test_drift_unnumbered_line_or_2000_lines_is_unknown(make_repo, tmp_path: Path) -> None:
    good = _read_text("a\nb\n")
    for text in (good + "\n<system-reminder>x</system-reminder>", "File is empty", "",
                 _read_text("l\n" * 1999)):
        read = _call("Read", {"file_path": "f.py"}, text, tmp_path)
        assert drift.full_read_blob(read) is None, text[:20]
    assert drift.full_read_blob(_call("Read", {"file_path": "f.py"}, good, tmp_path)) is not None


def test_drift_matches_relative_read_path_via_cwd(make_repo) -> None:
    repo = make_repo(BASE)
    read = _call("Read", {"file_path": "app/api.py"}, _read_text(BASE["app/api.py"]), repo.root)
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "no"
