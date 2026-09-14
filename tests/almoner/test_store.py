from datetime import datetime, timedelta, timezone

from scripts import store
from scripts.model import InMessage, conversation

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _item(pid: str, *, days_ago: float, text: str = "hello", context: str = "work",
          source: str = "notion"):
    at = NOW - timedelta(days=days_ago)
    return conversation(id=f"{source}:{pid}", source=source, context=context, title=pid,
                        messages=[InMessage(text=text, at=at, who="Rhona Baird", mine=False)])


def _ids(rows):
    return [r["id"] for r in rows]


class TestWindow:
    def test_days_bound_what_is_read_and_orders_newest_first(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("old", days_ago=20), _item("mid", days_ago=3),
                                  _item("new", days_ago=1)], NOW.timestamp())
        assert _ids(store.read_digest(conn, days=14, now=NOW.timestamp())) == [
            "notion:new", "notion:mid"]
        assert len(store.read_digest(conn, days=30, now=NOW.timestamp())) == 3

    def test_nothing_is_deleted_by_reading_a_narrow_window(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("old", days_ago=20)], NOW.timestamp())
        store.read_digest(conn, days=7, now=NOW.timestamp())
        assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 1

    def test_filters_by_context_and_source(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("a", days_ago=1, context="work"),
                                  _item("b", days_ago=1, context="home")], NOW.timestamp())
        assert _ids(store.read_digest(conn, days=14, now=NOW.timestamp(), context="home")) == [
            "notion:b"]
        assert store.read_digest(conn, days=14, now=NOW.timestamp(), source="slack") == []


class TestSeen:
    def test_new_only_returns_each_row_once(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("a", days_ago=1)], NOW.timestamp())
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp(), new_only=True)) == 1
        assert store.read_digest(conn, days=14, now=NOW.timestamp(), new_only=True) == []
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp())) == 1

    def test_reading_without_marking_leaves_rows_new(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("a", days_ago=1)], NOW.timestamp())
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp(), mark_shown=False)) == 1
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp(), new_only=True)) == 1

    def test_dismissal_hides_until_the_item_changes(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.upsert_items(conn, [_item("a", days_ago=1)], t)
        assert store.set_state(conn, "notion:a", "dismissed", t) is True
        store.upsert_items(conn, [_item("a", days_ago=1)], t + 60)  # unchanged re-fetch
        assert store.read_digest(conn, days=14, now=t) == []
        store.upsert_items(conn, [_item("a", days_ago=0.5, text="a new reply")], t + 120)
        assert _ids(store.read_digest(conn, days=14, now=t)) == ["notion:a"]

    def test_unknown_id_is_reported(self):
        conn = store.connect()
        assert store.set_state(conn, "notion:nope", "acted", NOW.timestamp()) is False


class TestBookkeeping:
    def test_watermark_round_trip(self):
        conn = store.connect()
        assert store.get_watermark(conn, "notion") is None
        store.set_watermark(conn, "notion", 123.0, cursor="c1")
        assert store.get_watermark(conn, "notion") == 123.0

    def test_runs_and_suppressed_are_logged(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.record_suppressed(conn, [("notion:x", "notion", "notion:no-open-comments")], t)
        store.record_suppressed(conn, [("notion:x", "notion", "notion:no-open-comments")], t + 1)
        run_id = store.record_run(conn, started=t, finished=t + 2, sources_ok=["notion"],
                                  sources_failed=[], items_in=3, items_out=2)
        runs = store.log_runs(conn)
        assert runs["runs"][0]["id"] == run_id and runs["runs"][0]["sources_ok"] == ["notion"]
        assert runs["store_bytes"] > 0
        [row] = store.log_suppressed(conn)["suppressed"]
        assert row["rule"] == "notion:no-open-comments" and row["at"] == t + 1
