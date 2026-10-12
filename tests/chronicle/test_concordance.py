import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from scripts import cli, concordance, ingest, report, store

from .conftest import TranscriptBuilder

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:00:05.000Z"
T2 = "2026-09-01T10:01:00.000Z"
T3 = "2026-09-01T10:02:00.000Z"


def _row(tid: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {"tool_use_id": tid, "agent_id": "", "kind": "grep",
                               "estimator": "callers", "covered": True, "actual_tokens": 3000,
                               "concordance_tokens": 300, "latency_ms": 900,
                               "answerable": "yes", "drifted": "unknown", "mode": "shadow"}
    base.update(kw)
    return base


def test_store_rows_drops_malformed_and_replaces(builder) -> None:
    conn = store.connect()
    assert concordance.store_rows(conn, "s", [_row("a"), {"tool_use_id": "b"}]) == 1
    assert concordance.store_rows(conn, "s", [_row("a"), _row("c")]) == 2
    assert conn.execute("SELECT COUNT(*) FROM concordance_rows").fetchone()[0] == 2


def test_store_rows_ignores_extra_keys_and_rejects_bad_types() -> None:
    conn = store.connect()
    rows = [_row("a", path="/secret"), _row("b", covered=1), _row("c", actual_tokens=True)]
    assert concordance.store_rows(conn, "s", rows) == 1
    cols = {r[1] for r in conn.execute("PRAGMA table_info(concordance_rows)")}
    assert "path" not in cols


def test_rows_never_hold_text_columns() -> None:
    conn = store.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(concordance_rows)")}
    assert not cols & {"path", "pattern", "command", "content", "file_path"}


def test_carried_cost_counts_later_turns(builder) -> None:
    path = (builder.turn("m1", T0, tools=["Grep"])
            .tool_result("r1", T1, tool_use_id="m1-tool0", content="x" * 9000)
            .turn("m2", T2).turn("m3", T3).write())
    conn = store.connect()
    ingest.ingest_session(conn, path)
    sid = conn.execute("SELECT session_id FROM tool_calls").fetchone()[0]
    concordance.store_rows(conn, sid, [_row("m1-tool0")])
    out = report.concordance(conn)
    grep = out["by_kind"]["grep"]
    assert grep["calls"] == 1 and grep["actual_tokens"] == 3000
    assert grep["unpriced_turns"] == 0
    assert grep["actual_carried_usd"] > grep["concordance_carried_usd"] > 0
    assert out["by_mode"]["shadow"]["calls"] == 1 and out["sessions"] == 1


def test_row_without_tool_call_has_size_but_no_carried_cost() -> None:
    conn = store.connect()
    concordance.store_rows(conn, "s", [_row("a")])
    grep = report.concordance(conn)["by_kind"]["grep"]
    assert grep["actual_tokens"] == 3000 and grep["actual_carried_usd"] == 0


def test_carried_cost_stops_at_compaction(builder) -> None:
    path = (builder.turn("m1", T0, tools=["Grep"])
            .tool_result("r1", T1, tool_use_id="m1-tool0", content="x")
            .turn("m2", T2).turn("m3", T3).write())
    conn = store.connect()
    ingest.ingest_session(conn, path)
    sid = conn.execute("SELECT session_id FROM tool_calls").fetchone()[0]
    concordance.store_rows(conn, sid, [_row("m1-tool0")])
    full = report.concordance(conn)["by_kind"]["grep"]["actual_carried_usd"]
    m2_ts = conn.execute("SELECT ts FROM turns WHERE message_id = 'm2'").fetchone()[0]
    conn.execute("INSERT INTO events(session_id, uuid, agent_id, kind, ts) "
                 "VALUES (?, 'c1', '', 'compaction', ?)", (sid, m2_ts + 1))
    half = report.concordance(conn)["by_kind"]["grep"]["actual_carried_usd"]
    assert 0 < half < full


def test_repo_filter_excludes_other_roots() -> None:
    conn = store.connect()
    concordance.store_rows(conn, "s", [_row("a")])
    assert report.concordance(conn, repo_root="/nowhere")["rows"] == 0


def test_concordance_verb_prints_json(builder, capsys) -> None:
    conn = store.connect()
    concordance.store_rows(conn, "s", [_row("a")])
    conn.close()
    assert cli.main(["concordance"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 1


PER_TURN = 3000 * 0.5 / 1_000_000   # actual_tokens x opus-5 cache-read $/Mtok


def _seeded(builder, projects):
    builder.turn("m1", T0, tools=["Grep"]).tool_result(
        "r1", T1, tool_use_id="m1-tool0", content="x").turn("m2", T2).turn("m3", T3).write()
    conn = store.connect()
    ingest.sync(conn, projects)
    sid = conn.execute("SELECT session_id FROM tool_calls").fetchone()[0]
    return conn, sid


def test_unpriced_turns_are_counted_not_charged(builder, projects) -> None:
    conn, sid = _seeded(builder, projects)
    concordance.store_rows(conn, sid, [_row("m1-tool0")])
    conn.execute("UPDATE turns SET model = 'mystery-9'")
    grep = report.concordance(conn)["by_kind"]["grep"]
    assert grep["unpriced_turns"] == 2 and grep["actual_carried_usd"] == 0


def test_mixed_priced_and_unpriced_turns(builder, projects) -> None:
    conn, sid = _seeded(builder, projects)
    concordance.store_rows(conn, sid, [_row("m1-tool0")])
    conn.execute("UPDATE turns SET model = 'mystery-9' WHERE message_id = 'm2'")
    grep = report.concordance(conn)["by_kind"]["grep"]
    assert grep["unpriced_turns"] == 1
    assert abs(grep["actual_carried_usd"] - PER_TURN) < 1e-9


def test_repo_and_since_filters_include_matches(builder, projects) -> None:
    conn, sid = _seeded(builder, projects)
    concordance.store_rows(conn, sid, [_row("m1-tool0")])
    conn.execute("UPDATE sessions SET repo_root = '/repo', last_activity_at = 1000.0")
    assert report.concordance(conn, repo_root="/repo")["rows"] == 1
    assert report.concordance(conn, repo_root="/other")["rows"] == 0
    assert report.concordance(conn, since=999.0)["rows"] == 1
    assert report.concordance(conn, since=1001.0)["rows"] == 0


def test_carried_cost_is_scoped_to_the_rows_agent(builder, projects) -> None:
    builder.turn("m1", T0, tools=["Grep"]).turn("m2", T2).turn("m3", T3)
    builder.subagent("ag1", ["a1", "a2", "a3"], T2, tools=["Grep"])
    builder.write()
    conn = store.connect()
    ingest.sync(conn, projects)
    sid = conn.execute("SELECT session_id FROM tool_calls").fetchone()[0]
    conn.execute("UPDATE tool_calls SET result_ts = (SELECT ts FROM turns WHERE message_id = 'm1') + 1 "
                 "WHERE agent_id = ''")
    conn.execute("UPDATE tool_calls SET result_ts = (SELECT MIN(ts) FROM turns) - 1 "
                 "WHERE agent_id = 'ag1'")
    main_id = conn.execute("SELECT tool_use_id FROM tool_calls WHERE agent_id = ''").fetchone()[0]
    agent_id = conn.execute(
        "SELECT tool_use_id FROM tool_calls WHERE agent_id = 'ag1' LIMIT 1").fetchone()[0]
    concordance.store_rows(conn, sid, [_row(main_id, kind="main"),
                                       _row(agent_id, kind="agent", agent_id="ag1")])
    out = report.concordance(conn)["by_kind"]
    assert abs(out["main"]["actual_carried_usd"] - 2 * PER_TURN) < 1e-9
    assert abs(out["agent"]["actual_carried_usd"] - 3 * PER_TURN) < 1e-9


def test_store_rows_returns_rows_actually_stored_when_ids_repeat() -> None:
    conn = store.connect()
    assert concordance.store_rows(conn, "s", [_row("a"), _row("a", kind="read")]) == 1
    assert conn.execute("SELECT COUNT(*) FROM concordance_rows").fetchone()[0] == 1


def _finished_session(builder) -> tuple:
    path = (builder.turn("m1", T0, tools=["Grep"])
            .tool_result("r1", T1, tool_use_id="m1-tool0", content="x").write())
    conn = store.connect()
    ingest.ingest_session(conn, path)
    sid = conn.execute("SELECT session_id FROM sessions").fetchone()[0]
    return conn, sid


def _fake_cli(tmp_path: Path) -> dict[str, str]:
    cli = tmp_path / "cli.py"
    cli.write_text("# fake\n")
    return {"CONCORDANCE_CLI": str(cli)}


def test_sync_step_replays_and_marks(builder, tmp_path, monkeypatch) -> None:
    conn, sid = _finished_session(builder)
    calls = []

    def fake(cmd, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps([_row("m1-tool0")]), "")

    monkeypatch.setattr(concordance, "_exec", fake)
    env = _fake_cli(tmp_path)
    assert concordance.sync_step(conn, now=time.time() + 10**7, env=env)["replayed"] == 1
    assert "--session" in calls[0] and sid in calls[0]
    assert concordance.sync_step(conn, now=time.time() + 10**7, env=env)["replayed"] == 0


def test_sync_survives_replay_failure(builder, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)

    def boom(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(concordance, "_exec", boom)
    out = concordance.sync_step(conn, now=time.time() + 10**7, env=_fake_cli(tmp_path))
    assert out == {"replayed": 0, "failed": 1, "skipped": 0}


def test_failed_session_is_skipped_until_it_grows(builder, tmp_path, monkeypatch) -> None:
    conn, sid = _finished_session(builder)
    results = iter([subprocess.CompletedProcess([], 2, "", "err"),
                    subprocess.CompletedProcess([], 0, json.dumps([_row("m1-tool0")]), "")])
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: next(results))
    env = _fake_cli(tmp_path)
    later = time.time() + 10**7
    assert concordance.sync_step(conn, now=later, env=env)["failed"] == 1
    assert concordance.sync_step(conn, now=later, env=env) == {"replayed": 0, "failed": 0,
                                                              "skipped": 0}
    with conn:
        conn.execute("UPDATE sessions SET last_activity_at = last_activity_at + 1000 "
                     "WHERE session_id = ?", (sid,))
    assert concordance.sync_step(conn, now=later, env=env)["replayed"] == 1


def _more_sessions(projects, conn, n: int) -> list[str]:
    ids = []
    for k in range(n):
        b = TranscriptBuilder(projects, session_id=f"s{k + 2}")
        path = (b.turn(f"x{k}", f"2026-09-0{k + 2}T10:00:00.000Z", tools=["Grep"])
                .tool_result(f"r{k}", f"2026-09-0{k + 2}T10:00:05.000Z",
                             tool_use_id=f"x{k}-tool0", content="x").write())
        ingest.ingest_session(conn, path)
        ids.append(f"s{k + 2}")
    return ids


def test_failing_newest_does_not_starve_older(builder, projects, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    newest = _more_sessions(projects, conn, 1)[0]
    seen = []

    def fake(cmd, timeout):
        seen.append(cmd[cmd.index("--session") + 1])
        ok = cmd[cmd.index("--session") + 1] != newest
        return subprocess.CompletedProcess(cmd, 0 if ok else 2,
                                           json.dumps([_row("m1-tool0")]) if ok else "", "")

    monkeypatch.setattr(concordance, "_exec", fake)
    env, later = _fake_cli(tmp_path), time.time() + 10**7
    assert seen == [] and concordance.sync_step(conn, now=later, env=env, limit=1) == {
        "replayed": 0, "failed": 1, "skipped": 0}
    assert concordance.sync_step(conn, now=later, env=env, limit=1)["replayed"] == 1
    assert seen[0] == newest and seen[1] != newest


def test_limit_and_newest_first(builder, projects, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    _more_sessions(projects, conn, 2)
    seen = []

    def fake(cmd, timeout):
        seen.append(cmd[cmd.index("--session") + 1])
        return subprocess.CompletedProcess(cmd, 0, "[]", "")

    monkeypatch.setattr(concordance, "_exec", fake)
    out = concordance.sync_step(conn, now=time.time() + 10**7, env=_fake_cli(tmp_path), limit=2)
    assert out["replayed"] == 2 and seen == ["s3", "s2"]


def test_budget_stops_new_starts(builder, projects, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    _more_sessions(projects, conn, 2)
    ticks = iter(range(0, 10_000, 100))   # every clock() read advances 100 s
    seen = []

    def fake(cmd, timeout):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "[]", "")

    monkeypatch.setattr(concordance, "_exec", fake)
    out = concordance.sync_step(conn, now=time.time() + 10**7, env=_fake_cli(tmp_path),
                                budget=250, clock=lambda: float(next(ticks)))
    assert out["replayed"] == 2 and len(seen) == 2   # 3 candidates, third never started


def test_timeout_is_bounded(monkeypatch, tmp_path) -> None:
    got = []
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: got.append(timeout) or 1 / 0)
    with pytest.raises(ZeroDivisionError):
        concordance.run_replay(tmp_path / "c.py", "s", tmp_path / "t")
    assert got == [concordance.REPLAY_TIMEOUT] and concordance.REPLAY_TIMEOUT <= 120


def test_bad_output_counts_as_failed(builder, tmp_path, monkeypatch) -> None:
    for stdout in ("not json", '{"a": 1}'):
        conn, _ = _finished_session(builder)
        monkeypatch.setattr(concordance, "_exec",
                            lambda cmd, timeout, o=stdout: subprocess.CompletedProcess(cmd, 0, o, ""))
        out = concordance.sync_step(conn, now=time.time() + 10**7, env=_fake_cli(tmp_path))
        assert out["failed"] == 1 and out["replayed"] == 0
        conn.close()
        store.db_path().unlink()


def test_store_error_counts_as_failed(builder, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    monkeypatch.setattr(concordance, "_exec",
                        lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "[]", ""))

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk")

    monkeypatch.setattr(concordance, "store_rows", boom)
    out = concordance.sync_step(conn, now=time.time() + 10**7, env=_fake_cli(tmp_path))
    assert out == {"replayed": 0, "failed": 1, "skipped": 0}


def test_candidate_lookup_failure_is_logged(tmp_path, capsys) -> None:
    conn = sqlite3.connect(":memory:")   # no tables
    out = concordance.sync_step(conn, now=time.time(), env=_fake_cli(tmp_path))
    assert out["skipped"] == 1 and "candidate lookup skipped" in capsys.readouterr().err


def test_live_session_is_not_replayed(builder, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: 1 / 0)
    last = conn.execute("SELECT last_activity_at FROM sessions").fetchone()[0]
    out = concordance.sync_step(conn, now=last + 60, env=_fake_cli(tmp_path))
    assert out["replayed"] == 0 and out["failed"] == 0


def test_kill_switch_and_missing_cli(builder, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: 1 / 0)
    assert concordance.sync_step(conn, env={"CHRONICLE_NO_CONCORDANCE": "1"})["replayed"] == 0
    assert concordance.find_cli(env={}) is None


def test_cmd_sync_survives_concordance_blowup(builder, monkeypatch, capsys) -> None:
    def boom(conn):
        raise RuntimeError("nope")

    monkeypatch.setattr(concordance, "sync_step", boom)
    assert cli.main(["sync"]) == 0
    assert "concordance replay skipped" in capsys.readouterr().err
