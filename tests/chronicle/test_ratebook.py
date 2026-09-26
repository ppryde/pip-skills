"""RateBook: rates with history, selected by (model, timestamp)."""
import sqlite3

import pytest
from scripts import pricing, ratebook, store
from scripts.ratebook import RateBook, RateRow


def row(model, eff, inp, out, cr, *, w5=None, w1=None, source="t", observed=None):
    return RateRow(model, eff, inp, out, cr, w5, w1, source, observed if observed is not None else eff)


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "s.db")
    yield c
    c.close()


class TestSelection:
    def test_empty_book_equals_builtin_table(self):
        book = RateBook()
        for model in ("claude-opus-5", "claude-opus-5-5", "claude-haiku-4-5-20251001",
                      "claude-fable-5-1", "claude-fable-5", "claude-fable-50", "gpt-9", "", None):
            assert book.rates_for(model, 1_700_000_000) == pricing.rates_for(model)
            assert book.rates_for(model) == pricing.rates_for(model)

    def test_newest_row_at_or_before_ts(self):
        book = RateBook([row("m-1", 0, 5, 25, 0.5), row("m-1", 1000, 4, 20, 0.4),
                         row("m-1", 2000, 3, 15, 0.3)])
        assert book.rates_for("m-1", 999)["input"] == 5
        assert book.rates_for("m-1", 1000)["input"] == 4      # at the boundary: the new rate
        assert book.rates_for("m-1", 1999.9)["input"] == 4
        assert book.rates_for("m-1", 2000)["input"] == 3
        assert book.rates_for("m-1", 10**12)["input"] == 3

    def test_ts_none_or_zero_is_newest(self):
        book = RateBook([row("m-1", 0, 5, 25, 0.5), row("m-1", 1000, 4, 20, 0.4)])
        assert book.rates_for("m-1", None)["input"] == 4
        assert book.rates_for("m-1", 0)["input"] == 4
        assert book.rates_for("m-1")["input"] == 4

    def test_before_first_row_uses_first_row(self):
        # A model first SEEN at t=1000 existed before it was seen: its earliest
        # known rate applies to earlier turns rather than leaving them unpriced.
        book = RateBook([row("m-1", 1000, 4, 20, 0.4), row("m-1", 2000, 3, 15, 0.3)])
        assert book.rates_for("m-1", 5)["input"] == 4

    def test_prefix_and_longest_prefix(self):
        book = RateBook([row("claude-fable-5", 0, 10, 50, 1.0), row("claude-fable-5-1", 0, 10, 50, 0.25)])
        assert book.rates_for("claude-fable-5-1-20260101", 5)["cache_read"] == 0.25
        assert book.rates_for("claude-fable-5-20260101", 5)["cache_read"] == 1.0
        assert book.rates_for("claude-fable-50", 5) is None

    def test_model_absent_from_book_falls_back_to_builtin(self):
        book = RateBook([row("only-this", 0, 1, 2, 0.1)])
        assert book.rates_for("claude-opus-5", 1) == pricing.rates_for("claude-opus-5")
        assert book.rates_for("only-this", 1)["input"] == 1

    def test_db_rows_replace_builtin_for_that_model(self):
        book = RateBook([row("claude-opus-5", 0, 9, 9, 0.9)])
        assert book.rates_for("claude-opus-5", 1)["input"] == 9
        # ...and a builtin model the DB does not carry is unaffected, including
        # the one an id would otherwise prefix-match.
        assert book.rates_for("claude-opus-5-5", 1) == pricing.rates_for("claude-opus-5-5")

    def test_explicit_cache_writes_are_carried_when_present(self):
        book = RateBook([row("m", 0, 5, 25, 0.5, w5=6.0, w1=11.0)])
        r = book.rates_for("m", 1)
        assert r["cache_write_5m"] == 6.0 and r["cache_write_1h"] == 11.0
        assert "cache_write_5m" not in RateBook([row("m", 0, 5, 25, 0.5)]).rates_for("m", 1)


class TestPeriods:
    def test_boundaries_are_change_points_only(self):
        book = RateBook([row("a", 0, 1, 1, 1), row("a", 500, 2, 2, 2), row("b", 900, 1, 1, 1),
                         row("b", 700, 2, 2, 2)])
        # a's first row (0) and b's first row (700) are not changes; the later ones are.
        assert book.boundaries == [500.0, 900.0]

    def test_period_sql_and_representative_ts(self):
        book = RateBook([row("a", 0, 1, 1, 1), row("a", 500, 2, 2, 2), row("a", 900, 3, 3, 3)])
        assert book.boundaries == [500.0, 900.0]
        sql = book.period_sql("t.ts")
        conn = sqlite3.connect(":memory:")
        got = [conn.execute(f"SELECT {sql.replace('t.ts', '?')}", (v,) * sql.count("t.ts")).fetchone()[0]
               for v in (None, 0, 499, 500, 899, 900, 10**9)]
        assert got == [-1, 0, 0, 1, 1, 2, 2]
        assert book.period_ts(-1) is None
        assert book.rates_for("a", book.period_ts(0))["input"] == 1
        assert book.rates_for("a", book.period_ts(1))["input"] == 2
        assert book.rates_for("a", book.period_ts(2))["input"] == 3

    def test_no_boundaries_is_constant_period(self):
        book = RateBook([row("a", 0, 1, 1, 1)])
        assert book.boundaries == []
        assert book.period_sql("t.ts") == "0"
        assert book.rates_for("a", book.period_ts(0))["input"] == 1


class TestSummaries:
    def test_pricing_as_of_is_newest_observation(self):
        assert RateBook().pricing_as_of() == pricing.PRICING_AS_OF
        book = RateBook([row("a", 0, 1, 1, 1, observed=1_790_000_000),
                         row("a", 5, 2, 2, 2, observed=1_790_100_000)])
        assert book.pricing_as_of() == "2026-09-22"

    def test_changes_since(self):
        book = RateBook([row("a", 0, 1, 1, 1), row("a", 500, 2, 2, 2, source="x"),
                         row("b", 900, 1, 1, 1)])
        allc = book.changes_since(None)
        assert [(c["model"], c["effective_from"]) for c in allc] == [("a", 500.0)]
        assert allc[0]["previous"]["input"] == 1 and allc[0]["current"]["input"] == 2
        assert allc[0]["source"] == "x"
        assert book.changes_since(501) == []


class TestStorage:
    def test_table_exists_on_connect_and_pk_is_model_effective_from(self, conn):
        assert ratebook.has_table(conn)
        pk = [r[1] for r in sorted(conn.execute("PRAGMA table_info(price_history)"),
                                   key=lambda r: r[5]) if r[5]]
        assert pk == ["model", "effective_from"]

    def test_insert_is_append_only_and_ignores_duplicates(self, conn):
        assert ratebook.insert_rows(conn, [row("m", 0, 1, 2, 0.1)]) == 1
        assert ratebook.insert_rows(conn, [row("m", 0, 9, 9, 9)]) == 0     # same key: kept as-is
        assert ratebook.load(conn).rates_for("m", 5)["input"] == 1

    def test_seed_builtin_inserts_each_model_once_at_zero(self, conn):
        n = ratebook.seed_builtin(conn)
        assert n == len(pricing._RATES)
        assert ratebook.seed_builtin(conn) == 0
        rows = ratebook.load_rows(conn)
        assert {r.effective_from for r in rows} == {0.0}
        assert {r.source for r in rows} == {"builtin"}
        # Seeded book prices exactly like the built-in table, cache writes explicit.
        book = ratebook.load(conn)
        for model in pricing._RATES:
            got = book.rates_for(model, 5)
            want = pricing.rates_for(model)
            assert (got["input"], got["output"], got["cache_read"]) == (
                want["input"], want["output"], want["cache_read"])
            assert got["cache_write_5m"] == want["input"] * pricing.CACHE_WRITE_5M_MULTIPLIER
            assert got["cache_write_1h"] == want["input"] * pricing.CACHE_WRITE_1H_MULTIPLIER
        assert book.pricing_as_of() == pricing.PRICING_AS_OF

    def test_seed_does_not_touch_a_model_that_already_has_history(self, conn):
        ratebook.insert_rows(conn, [row("claude-opus-5", 1000, 9, 9, 9)])
        ratebook.seed_builtin(conn)
        assert [r.input for r in ratebook.load_rows(conn) if r.model == "claude-opus-5"] == [9]

    def test_load_on_unmigrated_readonly_store_is_the_empty_book(self, tmp_path):
        path = tmp_path / "old.db"
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        c.commit()
        c.close()
        ro = store.connect(path, readonly=True)
        assert not ratebook.has_table(ro)
        assert ratebook.load(ro).rates_for("claude-opus-5", 1) == pricing.rates_for("claude-opus-5")
        ro.close()
