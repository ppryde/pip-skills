"""Point-in-time costing: a turn is priced at the rate in force when it ran."""
import shutil
import sqlite3

import pytest
from scripts import dedupe, ingest, pricing, ratebook, report, store
from scripts.ratebook import RateRow
from scripts.transcript import parse_ts

from .conftest import TranscriptBuilder

DAY1 = "2026-09-01T10:00:00.000Z"
DAY2 = "2026-09-02T10:00:00.000Z"
# Opus 5 changes rate between the two days. Every seeded turn is the conftest's
# default usage: 3 input, 1000 cache-read, 200 cache-write (no TTL split, so
# 5-minute), 40 output.
CHANGE_AT = parse_ts("2026-09-02T00:00:00.000Z")


def usd(inp, out, cr, cw5):
    return (3 * inp + 1000 * cr + 200 * cw5 + 40 * out) / 1_000_000


OLD = usd(5.0, 25.0, 0.5, 6.25)          # the built-in opus-5 row
NEW = usd(4.0, 20.0, 0.4, 5.5)           # explicit cache-write dollars, not 1.25x


def _rows():
    return [
        RateRow("claude-opus-5", 0.0, 5.0, 25.0, 0.5, 6.25, 10.0, "builtin", 1_790_000_000.0),
        RateRow("claude-opus-5", CHANGE_AT, 4.0, 20.0, 0.4, 5.5, 9.0, "pricing-page@2026-09-02",
                1_790_100_000.0),
    ]


def _store(projects, *, with_history):
    b = TranscriptBuilder(projects, "-a", "s1")
    b.prompt("u1", DAY1).turn("m1", DAY1).turn("m2", DAY1).turn("m3", DAY2)
    b.subagent("ag1", ["a1", "a2"], DAY2, task="t")
    b.write()
    conn = store.connect()
    ingest.sync(conn, projects)
    conn.execute("UPDATE sessions SET account_uuid = 'acct'")
    if with_history:
        ratebook.insert_rows(conn, _rows())
    conn.commit()
    return conn


class TestPointInTime:
    def test_summary_prices_each_side_of_the_change_at_its_own_rate(self, projects):
        conn = _store(projects, with_history=True)
        out = report.summary(conn)
        assert out["totals"]["cost_usd"] == pytest.approx(2 * OLD + 3 * NEW, abs=1e-6)
        days = {d["day"]: d["cost_usd"] for d in out["by_day"]}
        assert days["2026-09-01"] == pytest.approx(2 * OLD, abs=1e-6)
        assert days["2026-09-02"] == pytest.approx(3 * NEW, abs=1e-6)
        (model,) = out["by_model"]
        assert model["cost_usd"] == pytest.approx(2 * OLD + 3 * NEW, abs=1e-6)
        assert out["totals"]["unpriced_turns"] == 0

    def test_a_session_spanning_the_change_sums_both_rates(self, projects):
        conn = _store(projects, with_history=True)
        (row,) = report.sessions(conn)
        assert row["cost_usd"] == pytest.approx(2 * OLD + 3 * NEW, abs=1e-6)
        detail = report.session_detail(conn, "s1")
        assert detail["cost_usd"] == pytest.approx(2 * OLD + 3 * NEW, abs=1e-6)
        assert [round(t["cost_usd"], 9) for t in detail["turn_series"]] == [
            round(OLD, 9), round(OLD, 9), round(NEW, 9)]

    def test_agent_detail_is_priced_at_the_agents_own_time(self, projects):
        conn = _store(projects, with_history=True)
        agent = report.agent_detail(conn, "s1", "ag1")
        assert agent["cost_usd"] == pytest.approx(2 * NEW, abs=1e-6)
        assert [round(t["cost_usd"], 9) for t in agent["turn_series"]] == [round(NEW, 9)] * 2
        sub = report.session_detail(conn, "s1")["subagents"][0]
        assert sub["cost_usd"] == pytest.approx(2 * NEW, abs=1e-6)

    def test_limits_window_sum_is_point_in_time(self, projects):
        conn = _store(projects, with_history=True)
        start, end = parse_ts(DAY1) - 1, parse_ts(DAY2) + 1
        both = report._sum_account_tokens(conn, "acct", start, end)
        assert both["cost_usd"] == pytest.approx(2 * OLD + 3 * NEW, abs=1e-6)
        before = report._sum_account_tokens(conn, "acct", start, CHANGE_AT - 1)
        assert before["cost_usd"] == pytest.approx(2 * OLD, abs=1e-6)

    def test_boundary_turn_takes_the_new_rate(self, projects):
        conn = _store(projects, with_history=True)
        conn.execute("UPDATE turns SET ts = ? WHERE message_id = 'm3'", (CHANGE_AT,))
        conn.commit()
        detail = report.session_detail(conn, "s1")
        assert detail["turn_series"][-1]["cost_usd"] == pytest.approx(NEW, abs=1e-9)

    def test_dedupe_dry_run_prices_at_the_turns_time(self, projects):
        conn = _store(projects, with_history=True)
        conn.execute("UPDATE turns SET output_tokens = 10000000 WHERE message_id = 'm3'")
        conn.execute("""INSERT INTO turns(session_id, agent_id, message_id, ts, model, input_tokens,
                        cache_read_tokens, cache_creation_tokens, output_tokens)
                        SELECT session_id, 'ag-dup', message_id, ts, model, input_tokens,
                        cache_read_tokens, cache_creation_tokens, output_tokens
                        FROM turns WHERE message_id = 'm3' AND agent_id = ''""")
        conn.commit()
        res = dedupe.dedupe(conn)
        assert res["rows_removed"] == 1
        # 10M output tokens: $200 at the new rate ($250 at the old one).
        assert res["cost_usd_removed"] == round(NEW + 10_000_000 * 20.0 / 1_000_000 - 40 * 20.0 / 1_000_000, 2)


class TestNoHistoryEqualsToday:
    def test_empty_price_history_gives_the_builtin_numbers(self, projects):
        conn = _store(projects, with_history=False)
        out = report.summary(conn)
        assert out["totals"]["cost_usd"] == pytest.approx(5 * OLD, abs=1e-6)
        assert out["totals"]["pricing_as_of"] == pricing.PRICING_AS_OF
        assert out["totals"]["rates_changed"] == []

    def test_seeded_history_gives_the_same_numbers_as_empty(self, projects):
        conn = _store(projects, with_history=False)
        before = report.summary(conn)
        ratebook.seed_builtin(conn)
        conn.commit()
        after = report.summary(conn)
        assert after["totals"]["cost_usd"] == before["totals"]["cost_usd"]
        assert after["by_day"] == before["by_day"]
        assert after["totals"]["pricing_as_of"] == pricing.PRICING_AS_OF

    def test_unmigrated_readonly_store_still_reports(self, projects, tmp_path):
        conn = _store(projects, with_history=True)
        conn.close()
        legacy = tmp_path / "legacy.db"
        shutil.copy(store.db_path(), legacy)
        raw = sqlite3.connect(legacy)
        raw.execute("DROP TABLE price_history")
        raw.commit()
        raw.close()
        ro = store.connect(legacy, readonly=True)
        out = report.summary(ro)
        assert out["totals"]["cost_usd"] == pytest.approx(5 * OLD, abs=1e-6)
        assert report.session_detail(ro, "s1")["cost_usd"] == pytest.approx(5 * OLD, abs=1e-6)
        ro.close()

    def test_unknown_model_stays_unpriced_with_history_present(self, projects):
        conn = _store(projects, with_history=True)
        conn.execute("UPDATE turns SET model = 'mystery-9' WHERE message_id = 'm1'")
        conn.commit()
        out = report.summary(conn)
        assert out["totals"]["unpriced_turns"] == 1
        assert out["totals"]["cost_usd"] == pytest.approx(1 * OLD + 3 * NEW, abs=1e-6)
        models = {m["model"]: m["cost_usd"] for m in out["by_model"]}
        assert models["mystery-9"] is None


class TestReportMetadata:
    def test_pricing_as_of_and_rates_changed(self, projects):
        conn = _store(projects, with_history=True)
        totals = report.summary(conn)["totals"]
        assert totals["pricing_as_of"] == "2026-09-22"          # newest observed_at
        (change,) = totals["rates_changed"]
        assert change["model"] == "claude-opus-5" and change["effective_from"] == CHANGE_AT
        assert change["previous"]["input"] == 5.0 and change["current"]["input"] == 4.0

    def test_rates_changed_only_lists_changes_inside_the_window(self, projects):
        conn = _store(projects, with_history=True)
        assert report.summary(conn, since=CHANGE_AT - 10)["totals"]["rates_changed"] != []
        assert report.summary(conn, since=CHANGE_AT + 10)["totals"]["rates_changed"] == []
