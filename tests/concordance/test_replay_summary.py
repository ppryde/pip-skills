from pathlib import Path

from scripts.replay import store


def _row(tid: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "session_id": "s1", "tool_use_id": tid, "agent_id": "", "kind": "grep",
        "estimator": "callers", "covered": True, "actual_tokens": 1000,
        "concordance_tokens": 100, "latency_ms": 5, "exit_code": 0, "answerable": "yes",
        "drifted": "unknown", "mode": "shadow"}
    base.update(kw)
    return base


def test_uncovered_rows_contribute_no_saving_and_sums_split_by_answerable(tmp_path: Path) -> None:
    db = tmp_path / "usage.db"
    store.save([
        _row("a"),                                                   # covered, yes: saves 900
        _row("b", answerable="no", concordance_tokens=400),          # covered, no: saves 600
        _row("c", answerable="unknown", concordance_tokens=50),      # covered, unknown
        _row("d", covered=False, concordance_tokens=0, answerable="unknown",
             actual_tokens=5000),                                    # uncovered: no saving
    ], db)
    grep = store.summary(path=db)["by_kind"]["grep"]
    assert grep["calls"] == 4 and grep["covered"] == 3 and grep["uncovered"] == 1
    assert grep["actual_tokens"] == 8000
    assert grep["counterfactual_tokens"] == 100 + 400 + 50 + 5000
    by = grep["by_answerable"]
    assert by["yes"] == {"calls": 1, "actual_tokens": 1000, "counterfactual_tokens": 100}
    assert by["no"] == {"calls": 1, "actual_tokens": 1000, "counterfactual_tokens": 400}
    assert by["unknown"] == {"calls": 2, "actual_tokens": 6000, "counterfactual_tokens": 5050}
    assert store.summary(path=db)["uncovered"] == 1


def test_a_kind_with_only_uncovered_rows_saves_nothing(tmp_path: Path) -> None:
    db = tmp_path / "usage.db"
    store.save([_row("a", kind="read", covered=False, concordance_tokens=0,
                     answerable="unknown", actual_tokens=2000)], db)
    read = store.summary(path=db)["by_kind"]["read"]
    assert read["actual_tokens"] == read["counterfactual_tokens"] == 2000
