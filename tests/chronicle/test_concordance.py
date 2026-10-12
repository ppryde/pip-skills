import json

from scripts import cli, concordance, ingest, report, store

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
