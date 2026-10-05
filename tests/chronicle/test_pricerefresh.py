"""Refreshing rates from the pricing page: append-only, idempotent, soft-failing."""
import json
import time

import pytest
from scripts import cli, pricepage, pricerefresh, pricing, ratebook, store
from scripts.pricepage import FetchError

from .conftest import TranscriptBuilder

NOW = 1_790_400_000.0          # 2026-09-26


def page(rows):
    """A markdown pricing page from (name, input, cw5, cw1, read, output) rows."""
    head = ("| Model | Base input tokens | 5m cache writes | 1h cache writes | "
            "Cache hits and refreshes | Output tokens |\n| --- | --- | --- | --- | --- | --- |\n")

    def usd(v):
        return f"${v:g} / MTok"
    return head + "".join(
        f"| {n} | {usd(i)} | {usd(w5)} | {usd(w1)} | {usd(r)} | {usd(o)} |\n"
        for n, i, w5, w1, r, o in rows)


def builtin_page():
    """The page as it would read if it matched the built-in table exactly."""
    names = {"claude-fable-5-1": "Fable 5.1", "claude-mythos-5-1": "Mythos 5.1",
             "claude-fable-5": "Fable 5", "claude-mythos-5": "Mythos 5", "claude-opus-5-5": "Opus 5.5",
             "claude-opus-5": "Opus 5", "claude-opus-4-8": "Opus 4.8", "claude-opus-4-7": "Opus 4.7",
             "claude-opus-4-6": "Opus 4.6", "claude-sonnet-5": "Sonnet 5",
             "claude-sonnet-4-6": "Sonnet 4.6", "claude-haiku-4-5": "Haiku 4.5"}
    return page([(f"Claude {names[m]}", r["input"], r["input"] * 1.25, r["input"] * 2,
                  r["cache_read"], r["output"]) for m, r in pricing._RATES.items()])


@pytest.fixture
def conn(tmp_path):
    c = store.connect()
    yield c
    c.close()


@pytest.fixture
def serve(monkeypatch):
    """Serve `text` as the pricing page; count fetches. No network, ever."""
    state = {"text": builtin_page(), "calls": 0, "error": None}

    def fake(url, *, timeout=5.0, max_bytes=0):
        state["calls"] += 1
        if state["error"] is not None:
            raise state["error"]
        return state["text"]
    monkeypatch.setattr(pricepage, "fetch_text", fake)
    return state


def rows(conn):
    return [(r.model, r.effective_from, r.source) for r in ratebook.load_rows(conn)]


class TestRefresh:
    def test_first_refresh_seeds_then_a_second_writes_nothing(self, conn, serve):
        first = pricerefresh.refresh(conn, now=NOW)
        assert first["status"] == "unchanged" and first["seeded"] == len(pricing._RATES)
        assert first["changed"] == [] and first["added"] == []
        before = ratebook.load_rows(conn)
        second = pricerefresh.refresh(conn, now=NOW + 3600)
        assert second["status"] == "unchanged" and second["seeded"] == 0
        assert ratebook.load_rows(conn) == before

    def test_a_changed_rate_appends_a_row_stamped_with_the_observation_time(self, conn, serve):
        pricerefresh.refresh(conn, now=NOW)
        serve["text"] = builtin_page().replace("| Claude Opus 5 | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.5 / MTok | $25 / MTok |",
                                                "| Claude Opus 5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.4 / MTok | $20 / MTok |")
        res = pricerefresh.refresh(conn, now=NOW + 86400)
        assert res["status"] == "changed" and res["changed"] == ["claude-opus-5"]
        got = [r for r in ratebook.load_rows(conn) if r.model == "claude-opus-5"]
        assert [r.effective_from for r in got] == [0.0, NOW + 86400]
        new = got[1]
        assert (new.input, new.output, new.cache_read, new.cache_write_5m, new.cache_write_1h) == (
            4.0, 20.0, 0.4, 5.0, 8.0)
        assert new.source == "pricing-page@2026-09-27" and new.observed_at == NOW + 86400
        # The old rate still applies before the observation, the new one from it.
        book = ratebook.load(conn)
        assert book.rates_for("claude-opus-5", NOW)["input"] == 5.0
        assert book.rates_for("claude-opus-5", NOW + 86400)["input"] == 4.0
        # ...and only that model changed: no other model gained a row.
        assert sum(1 for r in ratebook.load_rows(conn) if r.effective_from > 0) == 1
        # Idempotent from here.
        again = pricerefresh.refresh(conn, now=NOW + 2 * 86400)
        assert again["status"] == "unchanged"

    def test_a_new_model_gets_a_row(self, conn, serve):
        serve["text"] += "| Claude Opus 6 | $6 / MTok | $7.50 / MTok | $12 / MTok | $0.60 / MTok | $30 / MTok |\n"
        res = pricerefresh.refresh(conn, now=NOW)
        assert res["status"] == "changed" and res["added"] == ["claude-opus-6"]
        (row,) = [r for r in ratebook.load_rows(conn) if r.model == "claude-opus-6"]
        assert row.effective_from == NOW and row.input == 6.0
        assert ratebook.load(conn).rates_for("claude-opus-6-20270101", NOW + 1)["output"] == 30.0

    def test_a_missing_cache_write_column_is_not_a_change(self, conn, serve):
        pricerefresh.refresh(conn, now=NOW)
        serve["text"] = ("| Model | Input | Cache Hits | Output |\n| --- | --- | --- | --- |\n"
                         "| Claude Opus 5 | $5 / MTok | $0.50 / MTok | $25 / MTok |\n")
        assert pricerefresh.refresh(conn, now=NOW + 1)["status"] == "unchanged"

    def test_a_tenfold_change_is_refused_and_nothing_is_written(self, conn, serve):
        serve["text"] = page([("Claude Opus 5", 60.0, 75.0, 120.0, 6.0, 300.0)])
        res = pricerefresh.refresh(conn, now=NOW)
        assert res["status"] == "refused" and "claude-opus-5" in res["error"]
        assert rows(conn) == []                                 # not even the seed

    def test_dry_run_reports_and_writes_nothing(self, conn, serve):
        serve["text"] += "| Claude Opus 6 | $6 / MTok | $7.50 / MTok | $12 / MTok | $0.60 / MTok | $30 / MTok |\n"
        res = pricerefresh.refresh(conn, now=NOW, dry_run=True)
        assert res["status"] == "changed" and res["added"] == ["claude-opus-6"] and res["dry_run"]
        assert rows(conn) == []

    @pytest.mark.parametrize("failure", [FetchError("HTTP 503"), FetchError("timed out")])
    def test_a_network_error_is_a_soft_status(self, conn, serve, failure):
        serve["error"] = failure
        res = pricerefresh.refresh(conn, now=NOW)
        assert res["status"] == "error" and str(failure) in res["error"]
        assert rows(conn) == []

    def test_a_layout_surprise_writes_nothing(self, conn, serve):
        serve["text"] = "# Pricing\n\nWe redesigned this page. No tables.\n"
        res = pricerefresh.refresh(conn, now=NOW)
        assert res["status"] == "error" and rows(conn) == []

    def test_an_unexpected_exception_never_escapes(self, conn, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(pricepage, "fetch_text", boom)
        res = pricerefresh.refresh(conn, now=NOW)
        assert res["status"] == "error" and "kaboom" in res["error"]

    def test_existing_history_is_the_baseline_not_the_builtin(self, conn, serve):
        # Rates a backfill/refresh already moved on: the page matching them is no change.
        ratebook.seed_builtin(conn)
        ratebook.insert_rows(conn, [ratebook.RateRow("claude-opus-5", 1000.0, 4.0, 20.0, 0.4, 5.0, 8.0,
                                                     "x", 1000.0)])
        conn.commit()
        serve["text"] = page([("Claude Opus 5", 4.0, 5.0, 8.0, 0.4, 20.0)])
        assert pricerefresh.refresh(conn, now=NOW)["status"] == "unchanged"


class TestSeedAndStatus:
    def test_seed_is_idempotent(self, conn):
        assert pricerefresh.seed(conn)["seeded"] == len(pricing._RATES)
        assert pricerefresh.seed(conn)["seeded"] == 0

    def test_status_lists_ranges_and_last_attempt(self, conn, serve):
        pricerefresh.refresh(conn, now=NOW)
        pricerefresh.record_attempt(conn, {"status": "unchanged", "changed": [], "added": []}, NOW)
        serve["text"] = page([("Claude Opus 5", 4.0, 5.0, 8.0, 0.4, 20.0)])
        pricerefresh.refresh(conn, now=NOW + 100)
        conn.commit()
        out = pricerefresh.status(conn)
        assert out["pricing_as_of"] == "2026-09-26"
        opus = next(m for m in out["models"] if m["model"] == "claude-opus-5")
        assert [(p["effective_from"], p["effective_to"], p["input"]) for p in opus["periods"]] == [
            (0.0, NOW + 100, 5.0), (NOW + 100, None, 4.0)]
        assert out["last_refresh"]["status"] == "unchanged" and out["last_refresh"]["at"] == NOW
        assert out["rows"] == len(pricing._RATES) + 1

    def test_status_on_an_unmigrated_readonly_store(self, tmp_path):
        import sqlite3
        path = tmp_path / "old.db"
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        c.commit()
        c.close()
        ro = store.connect(path, readonly=True)
        out = pricerefresh.status(ro)
        assert out["rows"] == 0 and out["last_refresh"] is None
        assert out["pricing_as_of"] == pricing.PRICING_AS_OF
        ro.close()


class TestMaybeRefresh:
    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.delenv("CHRONICLE_NO_PRICING_REFRESH", raising=False)

    def test_env_switch_disables_it_without_touching_anything(self, conn, serve, monkeypatch):
        monkeypatch.setenv("CHRONICLE_NO_PRICING_REFRESH", "1")
        assert pricerefresh.maybe_refresh(conn, now=NOW) == {"status": "disabled", "changed": []}
        assert serve["calls"] == 0 and rows(conn) == []
        assert conn.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'pricing_%'").fetchone()[0] == 0

    def test_runs_at_most_once_a_day(self, conn, serve):
        first = pricerefresh.maybe_refresh(conn, now=NOW)
        assert first["status"] == "unchanged" and serve["calls"] == 1
        soon = pricerefresh.maybe_refresh(conn, now=NOW + 3600)
        assert soon["status"] == "skipped" and soon["changed"] == [] and serve["calls"] == 1
        later = pricerefresh.maybe_refresh(conn, now=NOW + 86400 + 1)
        assert later["status"] == "unchanged" and serve["calls"] == 2

    def test_a_failure_is_recorded_and_not_retried_every_minute(self, conn, serve):
        serve["error"] = FetchError("HTTP 503")
        res = pricerefresh.maybe_refresh(conn, now=NOW)
        assert res["status"] == "error"
        for minute in range(1, 6):
            assert pricerefresh.maybe_refresh(conn, now=NOW + 60 * minute)["status"] == "skipped"
        assert serve["calls"] == 1
        recorded = pricerefresh.status(conn)["last_refresh"]
        assert recorded["status"] == "error" and "503" in recorded["error"] and recorded["at"] == NOW

    def test_changes_are_reported_and_recorded(self, conn, serve):
        serve["text"] += "| Claude Opus 6 | $6 / MTok | $7.50 / MTok | $12 / MTok | $0.60 / MTok | $30 / MTok |\n"
        res = pricerefresh.maybe_refresh(conn, now=NOW)
        assert res["status"] == "changed" and res["added"] == ["claude-opus-6"]
        assert pricerefresh.status(conn)["last_refresh"]["added"] == ["claude-opus-6"]

    def test_never_raises(self, conn, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(pricepage, "fetch_text", boom)
        assert pricerefresh.maybe_refresh(conn, now=NOW)["status"] == "error"

    def test_an_unpriced_model_in_new_turns_triggers_one_early_retry(self, conn, serve, projects):
        pricerefresh.maybe_refresh(conn, now=NOW)                     # the daily run
        assert serve["calls"] == 1
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", "2026-09-26T10:00:00.000Z").turn(
            "m1", "2026-09-26T10:00:00.000Z", model="claude-newmodel-9").write()
        from scripts import ingest
        ingest.sync(conn, projects)
        # Not due (an hour later), but an unpriced model appeared: run early, once.
        early = pricerefresh.maybe_refresh(conn, now=NOW + 3600)
        assert early["status"] == "unchanged" and serve["calls"] == 2
        # The page still does not know it: it does not retry it again before the next daily run.
        assert pricerefresh.maybe_refresh(conn, now=NOW + 7200)["status"] == "skipped"
        assert serve["calls"] == 2

    def test_a_priced_model_does_not_trigger_an_early_run(self, conn, serve, projects):
        pricerefresh.maybe_refresh(conn, now=NOW)
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", "2026-09-26T10:00:00.000Z").turn(
            "m1", "2026-09-26T10:00:00.000Z", model="claude-opus-5-20261001").write()
        from scripts import ingest
        ingest.sync(conn, projects)
        assert pricerefresh.maybe_refresh(conn, now=NOW + 3600)["status"] == "skipped"
        assert serve["calls"] == 1


class TestSyncCarriesPricing:
    def test_sync_result_has_the_pricing_status_when_disabled(self, capsys):
        assert cli.main(["sync"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["pricing"] == {"status": "disabled", "changed": []}

    def test_sync_refreshes_softly_and_reports_it(self, capsys, serve, monkeypatch):
        monkeypatch.delenv("CHRONICLE_NO_PRICING_REFRESH", raising=False)
        serve["text"] += "| Claude Opus 6 | $6 / MTok | $7.50 / MTok | $12 / MTok | $0.60 / MTok | $30 / MTok |\n"
        assert cli.main(["sync"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["pricing"]["status"] == "changed" and out["pricing"]["added"] == ["claude-opus-6"]
        assert cli.main(["sync"]) == 0                                # a minute later: skipped
        assert json.loads(capsys.readouterr().out)["pricing"]["status"] == "skipped"

    def test_sync_never_fails_because_pricing_did(self, capsys, serve, monkeypatch):
        monkeypatch.delenv("CHRONICLE_NO_PRICING_REFRESH", raising=False)
        serve["error"] = FetchError("no route to host")
        assert cli.main(["sync"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["pricing"]["status"] == "error" and "sessions" in out


class TestVerbs:
    def test_refresh_dry_run_verb(self, capsys, serve):
        assert cli.main(["pricing", "refresh", "--dry-run"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "unchanged" and out["dry_run"] is True
        assert not store.db_path().exists() or rows(store.connect()) == []

    def test_refresh_verb_writes_and_records(self, capsys, serve):
        serve["text"] += "| Claude Opus 6 | $6 / MTok | $7.50 / MTok | $12 / MTok | $0.60 / MTok | $30 / MTok |\n"
        assert cli.main(["pricing", "refresh"]) == 0
        assert json.loads(capsys.readouterr().out)["added"] == ["claude-opus-6"]
        assert cli.main(["pricing", "status"]) == 0
        st = json.loads(capsys.readouterr().out)
        assert st["last_refresh"]["status"] == "changed"
        assert any(m["model"] == "claude-opus-6" for m in st["models"])

    def test_refresh_verb_exits_nonzero_on_error_but_prints_json(self, capsys, serve):
        serve["error"] = FetchError("HTTP 500")
        assert cli.main(["pricing", "refresh"]) == 1
        assert json.loads(capsys.readouterr().out)["status"] == "error"

    def test_seed_verb(self, capsys):
        assert cli.main(["pricing", "seed"]) == 0
        assert json.loads(capsys.readouterr().out)["seeded"] == len(pricing._RATES)

    def test_status_on_a_missing_store(self, capsys):
        assert cli.main(["pricing", "status"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["exists"] is False


def test_time_is_real_by_default(conn, serve):
    before = time.time()
    res = pricerefresh.refresh(conn)
    assert res["status"] == "unchanged"
    assert all(r.observed_at <= time.time() for r in ratebook.load_rows(conn)) and before <= time.time()
