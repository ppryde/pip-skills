import os
import sqlite3
from datetime import datetime, timedelta, timezone

from scripts import paths, store
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

    def test_dismissed_row_that_changes_is_returned_once_by_new_only(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.upsert_items(conn, [_item("a", days_ago=1)], t)
        store.read_digest(conn, days=14, now=t, new_only=True)  # shown_count -> 1, state shown
        assert store.set_state(conn, "notion:a", "dismissed", t) is True
        # Changed while dismissed: state resets to 'new', shown_count is left alone.
        store.upsert_items(conn, [_item("a", days_ago=0.5, text="a new reply")], t + 60)
        assert _ids(store.read_digest(conn, days=14, now=t, new_only=True)) == ["notion:a"]
        assert store.read_digest(conn, days=14, now=t, new_only=True) == []


class TestClosed:
    def test_a_closed_suppression_hides_the_item(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.upsert_items(conn, [_item("a", days_ago=1)], t)
        store.record_suppressed(conn, [("notion:a", "notion", "closed")], t + 1)
        assert store.read_digest(conn, days=14, now=t) == []

    def test_a_regather_after_closure_shows_it_again(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.upsert_items(conn, [_item("a", days_ago=1)], t)
        store.record_suppressed(conn, [("notion:a", "notion", "closed")], t + 1)
        assert store.read_digest(conn, days=14, now=t) == []
        store.upsert_items(conn, [_item("a", days_ago=0.1, text="reopened")], t + 60)
        assert _ids(store.read_digest(conn, days=14, now=t + 60)) == ["notion:a"]


class TestGatheredAt:
    def test_rows_carry_when_they_were_gathered(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.upsert_items(conn, [_item("a", days_ago=1)], t)
        [row] = store.read_digest(conn, days=14, now=t)
        assert row["gathered_at"] == t


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


def _sidecars(target):
    return [target.with_name(target.name + suffix) for suffix in ("-wal", "-shm")
            if target.with_name(target.name + suffix).exists()]


class TestPrivacy:
    """A db, home dir or WAL/SHM sidecar must never be born group/other
    readable — even under a loose ambient umask, and even when SQLite (not
    almoner) is the one creating the sidecar. Every test here forces the
    umask loose first so it fails on code that relies on a private ambient
    umask instead of enforcing one itself."""

    def test_fresh_store_is_private_end_to_end(self):
        # -wal/-shm exist only while the connection is open (WAL mode creates
        # them at schema-creation time and SQLite removes them on close), so
        # check before closing — that's the window the finding is about.
        old = os.umask(0o022)
        try:
            conn = store.connect()
            store.upsert_items(conn, [_item("a", days_ago=1)], NOW.timestamp())
            target = paths.db_path()
            assert target.parent.stat().st_mode & 0o077 == 0
            assert target.stat().st_mode & 0o077 == 0
            sidecars = _sidecars(target)
            assert sidecars
            for sidecar in sidecars:
                assert sidecar.stat().st_mode & 0o077 == 0
            conn.close()
        finally:
            os.umask(old)

    def test_pre_existing_loose_home_and_db_are_tightened(self):
        # Check the -wal's mode before closing: a clean close checkpoints and
        # removes it, so by the time the connection is closed there is
        # nothing left to have been tightened.
        old = os.umask(0o022)
        try:
            target = paths.db_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(target.parent, 0o755)
            target.write_text("")
            os.chmod(target, 0o644)
            wal = target.with_name(target.name + "-wal")
            wal.write_text("")
            os.chmod(wal, 0o644)
            conn = store.connect()
            assert target.parent.stat().st_mode & 0o077 == 0
            assert target.stat().st_mode & 0o077 == 0
            assert wal.stat().st_mode & 0o077 == 0
            conn.close()
        finally:
            os.umask(old)

    def test_process_umask_is_restored_after_connect(self):
        old = os.umask(0o022)
        try:
            conn = store.connect()
            conn.close()
            current = os.umask(0o022)
            os.umask(current)
            assert current == 0o022
        finally:
            os.umask(old)

    def test_connect_readonly_tightens_a_sidecar_beside_a_pre_fix_loose_db(self):
        # Simulates a db that predates this fix and was never re-tightened —
        # `status` only ever calls connect_readonly, never connect(), so
        # nothing else would fix it. SQLite mirrors the *existing* db file's
        # own mode onto any -wal/-shm it creates while reading, umask or no
        # umask, so wrapping the read in a private umask alone cannot close
        # this: the sidecar must be chmodded explicitly.
        target = paths.db_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(target))
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("CREATE TABLE t (x)")
        raw.commit()
        raw.close()
        os.chmod(target, 0o644)  # the loose, pre-fix state being migrated from
        old = os.umask(0o022)
        try:
            ro = store.connect_readonly()
            ro.execute("SELECT * FROM t").fetchall()
            sidecars = _sidecars(target)
            assert sidecars
            for sidecar in sidecars:
                assert sidecar.stat().st_mode & 0o077 == 0
            ro.close()
        finally:
            os.umask(old)
