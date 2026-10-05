"""Backfilling rate history from archived snapshots (recorded fixtures, no network)."""
import json
from pathlib import Path

import pytest
from scripts import cli, pricehistory, pricepage, ratebook, store
from scripts.pricepage import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
NOW = 1_790_400_000.0                      # 2026-09-26
SRC0, SRC1, SRC2 = pricehistory.SOURCE_URLS

TS1, TS2, TS3 = "20260601000000", "20260715000000", "20260801000000"
BODIES = {TS1: "archive_20260601.md", TS2: "archive_20260715.html", TS3: "archive_20260801.md"}


@pytest.fixture
def conn():
    c = store.connect()
    yield c
    c.close()


@pytest.fixture
def archive(monkeypatch):
    """A fake Archive: CDX for the first source lists three captures (+ a 404),
    the others none; snapshot bodies come from the fixtures. Records every URL."""
    state = {"urls": [], "fail": set(), "bodies": dict(BODIES), "override": {}}

    def fake(url, *, timeout=5.0, max_bytes=0):
        state["urls"].append(url)
        if "cdx/search/cdx" in url:
            return (FIXTURES / "archive_cdx.json").read_text() if f"url={SRC0}&" in url else "[]"
        ts = url.split("/web/")[1].split("id_")[0]
        if ts in state["fail"]:
            raise FetchError("HTTP 503")
        if ts in state["override"]:
            return state["override"][ts]
        return (FIXTURES / state["bodies"][ts]).read_text()
    monkeypatch.setattr(pricepage, "fetch_text", fake)
    return state


def run(conn, **kw):
    sleeps = []
    out = pricehistory.backfill(conn, now=NOW, sleep=sleeps.append, **kw)
    out["_sleeps"] = sleeps
    return out


def archive_rows(conn):
    return sorted((r.model, r.effective_from, r.input, r.source) for r in ratebook.load_rows(conn)
                  if r.source.startswith("archive@"))


class TestParsing:
    def test_cdx_keeps_only_successful_captures(self):
        text = (FIXTURES / "archive_cdx.json").read_text()
        assert pricehistory.parse_cdx(text) == [TS1, TS2, TS3]

    @pytest.mark.parametrize("text", ["", "[]", "not json", '[["timestamp"]]', '{"a": 1}',
                                      '[["foo","bar"],["1","2"]]'])
    def test_cdx_garbage_is_no_captures(self, text):
        assert pricehistory.parse_cdx(text) == []

    def test_timestamps_are_utc_epochs(self):
        assert pricehistory.epoch("20260715000000") == 1_784_073_600.0


class TestDiffing:
    def test_first_appearance_and_changes_become_rows_at_the_snapshot_time(self, conn, archive):
        out = run(conn)
        assert out["status"] == "ok" and out["found"] == 3 and out["processed"] == 3
        e = pricehistory.epoch
        assert archive_rows(conn) == [
            ("claude-haiku-4-5", e(TS1), 1.0, f"archive@{TS1}"),
            ("claude-opus-5", e(TS1), 5.0, f"archive@{TS1}"),
            ("claude-opus-5-5", e(TS2), 4.0, f"archive@{TS2}"),      # new model, from the HTML snapshot
            ("claude-sonnet-5", e(TS1), 3.0, f"archive@{TS1}"),
            ("claude-sonnet-5", e(TS2), 2.0, f"archive@{TS2}"),      # the price change
        ]                                                            # TS3 is unchanged: no rows
        kinds = {(r["model"], r["timestamp"]): r["kind"] for r in out["rows"]}
        assert kinds[("claude-sonnet-5", TS1)] == "first" and kinds[("claude-sonnet-5", TS2)] == "change"

    def test_html_and_markdown_snapshots_read_the_same(self, conn, archive):
        run(conn)
        book = ratebook.load(conn)
        e = pricehistory.epoch
        assert book.rates_for("claude-sonnet-5", e(TS1) + 1)["input"] == 3.0
        assert book.rates_for("claude-sonnet-5", e(TS2))["input"] == 2.0
        assert book.rates_for("claude-opus-5-5", e(TS3))["cache_write_5m"] == 5.0

    def test_earliest_archived_rate_prices_turns_before_the_first_snapshot(self, conn, archive):
        ratebook.seed_builtin(conn)                      # today's sonnet-5 is $2
        run(conn)
        book = ratebook.load(conn)
        assert book.rates_for("claude-sonnet-5", pricehistory.epoch(TS1) - 86400)["input"] == 3.0

    def test_dry_run_reports_rows_and_writes_nothing(self, conn, archive):
        out = run(conn, dry_run=True)
        assert len(out["rows"]) == 5 and out["dry_run"]
        assert ratebook.load_rows(conn) == []
        assert store_meta(conn) is None

    def test_a_tenfold_jump_skips_the_snapshot(self, conn, archive):
        # Sonnet 5 at 13x in the middle snapshot: a mis-parse, not a price change.
        archive["override"][TS2] = (FIXTURES / "archive_20260601.md").read_text().replace(
            "| Claude Sonnet 5 | $3 / MTok | $3.75 / MTok | $6 / MTok | $0.3 / MTok | $15 / MTok |",
            "| Claude Sonnet 5 | $40 / MTok | $50 / MTok | $80 / MTok | $4 / MTok | $200 / MTok |")
        out = run(conn)
        assert any(u["timestamp"] == TS2 and "10x" in u["error"] for u in out["unparseable"])
        assert store_meta(conn)[TS2] == "suspect"
        assert not any(r[1] == pricehistory.epoch(TS2) for r in archive_rows(conn))


def store_meta(conn):
    row = conn.execute("SELECT value FROM meta WHERE key = 'pricing_backfill_snapshots'").fetchone()
    return None if row is None else json.loads(row[0])


class TestPolitenessAndResume:
    def test_sequential_with_a_gap_between_every_request(self, conn, archive):
        out = run(conn)
        # 3 listings + 3 snapshots, one at a time, a second apart.
        assert out["requests"] == 6 and len(archive["urls"]) == 6
        assert out["_sleeps"] == [pricehistory.REQUEST_GAP_SECONDS] * 5

    def test_limit_caps_total_requests_and_the_rest_is_resumable(self, conn, archive):
        first = run(conn, limit=4)                         # 3 listings + 1 snapshot
        assert first["requests"] == 4 and first["limit_reached"] and first["processed"] == 1
        assert first["remaining"] == 2
        assert set(store_meta(conn)) == {TS1}
        second = run(conn, limit=10)
        assert second["already_done"] == 1 and second["processed"] == 2
        assert not second["limit_reached"]
        # No snapshot was fetched twice across the two runs.
        snaps = [u for u in archive["urls"] if "/web/" in u]
        assert len(snaps) == len(set(snaps)) == 3
        # ...and the result equals a single uninterrupted run.
        assert len(archive_rows(conn)) == 5
        third = run(conn)
        assert third["processed"] == 0 and third["already_done"] == 3 and third["rows"] == []

    def test_a_failed_fetch_is_skipped_reported_and_retried_next_time(self, conn, archive):
        archive["fail"].add(TS2)
        out = run(conn)
        assert out["processed"] == 2 and out["failed"] == [{"timestamp": TS2, "error": "HTTP 503"}]
        assert set(store_meta(conn)) == {TS1, TS3}           # TS2 is not marked done
        # TS3 was diffed against TS1's state: the price change is found there instead (upper bound).
        assert ("claude-sonnet-5", pricehistory.epoch(TS3), 2.0,
                f"archive@{TS3}") in archive_rows(conn)
        archive["fail"].clear()
        again = run(conn)
        assert again["processed"] == 1 and again["already_done"] == 2

    def test_an_unparseable_snapshot_is_recorded_and_not_refetched(self, conn, archive):
        archive["bodies"][TS2] = "archive_cdx.json"          # valid file, but not a price page
        out = run(conn)
        assert [u["timestamp"] for u in out["unparseable"]] == [TS2]
        assert store_meta(conn)[TS2] == "unparseable"
        before = len(archive["urls"])
        run(conn)
        assert not any(f"/web/{TS2}" in u for u in archive["urls"][before:])

    def test_from_month_bounds_the_listing(self, conn, archive):
        run(conn, since_month="2026-07")
        cdx = [u for u in archive["urls"] if "cdx/search/cdx" in u]
        assert all("from=20260701" in u for u in cdx)

    def test_listing_failure_everywhere_is_an_error_status_with_no_writes(self, conn, monkeypatch):
        def boom(url, **k):
            raise FetchError("no route")
        monkeypatch.setattr(pricepage, "fetch_text", boom)
        out = run(conn)
        assert out["status"] == "error" and out["found"] == 0
        assert ratebook.load_rows(conn) == []

    def test_never_raises(self, conn, monkeypatch):
        monkeypatch.setattr(pricepage, "fetch_text", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
        assert run(conn)["status"] == "error"


class TestVerb:
    @pytest.fixture(autouse=True)
    def _no_real_sleeping(self, monkeypatch):
        monkeypatch.setattr(pricehistory, "REQUEST_GAP_SECONDS", 0.0)

    def test_verb_dry_run(self, capsys, archive):
        assert cli.main(["pricing", "backfill", "--dry-run", "--limit", "20"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["dry_run"] and len(out["rows"]) == 5

    def test_verb_writes_and_status_shows_ranges(self, capsys, archive):
        assert cli.main(["pricing", "backfill"]) == 0
        capsys.readouterr()
        assert cli.main(["pricing", "status"]) == 0
        st = json.loads(capsys.readouterr().out)
        sonnet = next(m for m in st["models"] if m["model"] == "claude-sonnet-5")
        assert [p["input"] for p in sonnet["periods"]] == [3.0, 2.0]

    @pytest.mark.parametrize("args", [["--from", "2026-13"], ["--from", "yesterday"], ["--limit", "0"]])
    def test_invalid_input_is_exit_2(self, capsys, args):
        assert cli.main(["pricing", "backfill", *args]) == 2
        assert "error" in capsys.readouterr().err
