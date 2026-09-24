"""Per-turn account attribution (WF-118).

A Claude Code session can move between accounts mid-run: a `bridge-session`
record carries `ownerAccountUuid`, and `/login` re-emits it with a new owner.
So each TURN carries the owner in force when it was written, and the reports
attribute cost and tokens per turn rather than wholly to the session's
config-dir account.

Bridge records carry no timestamp, so ordering is by position in the JSONL.
"""
import itertools
import sqlite3

from scripts import ingest, store

from .conftest import TranscriptBuilder, _assistant

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:05:00.000Z"
T2 = "2026-09-01T10:10:00.000Z"


def _bridge(owner: str, session_id: str = "s1") -> dict:
    return {"type": "bridge-session", "sessionId": session_id,
            "ownerAccountUuid": owner, "ownerOrganizationUuid": f"org-{owner}"}


def _session(conn: sqlite3.Connection, sid: str = "s1") -> sqlite3.Row:
    return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (sid,)).fetchone()


def _stamps(conn: sqlite3.Connection, sid: str = "s1") -> dict[str, str | None]:
    return {
        r["message_id"]: r["account_uuid"]
        for r in conn.execute(
            "SELECT message_id, account_uuid FROM turns WHERE session_id = ?", (sid,))
    }


def _two_owner(builder: TranscriptBuilder) -> TranscriptBuilder:
    return (builder.turn("m0", T0)             # before any bridge record
            .raw(_bridge("acc-A"))
            .turn("m1", T0).turn("m2", T1)
            .raw(_bridge("acc-B"))
            .turn("m3", T1).turn("m4", T2))


EXPECTED = {"m0": None, "m1": "acc-A", "m2": "acc-A", "m3": "acc-B", "m4": "acc-B"}


class TestIngestStamps:
    def test_turns_are_stamped_with_the_owner_in_force_when_written(self, builder):
        path = _two_owner(builder).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert _stamps(conn) == EXPECTED

    def test_the_last_owner_is_persisted_and_the_first_stays_write_once(self, builder):
        path = _two_owner(builder).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        row = _session(conn)
        assert row["bridge_owner_uuid"] == "acc-B"
        assert row["owner_account_uuid"] == "acc-A"

    def test_a_session_without_a_bridge_record_stamps_nothing(self, builder):
        path = builder.turn("m1", T0).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert _stamps(conn) == {"m1": None}
        assert _session(conn)["bridge_owner_uuid"] is None

    def test_batches_split_between_a_bridge_record_and_its_turns_stamp_the_same(
            self, builder, tmp_path):
        _two_owner(builder)
        records = list(builder.records)
        # Seams fall right after each bridge record, so the owner has to be
        # carried across batches via the session row.
        seams = [0, 2, 5, 6, len(records)]
        conn = store.connect(tmp_path / "split.db")
        builder.records = []
        for lo, hi in itertools.pairwise(seams):
            for record in records[lo:hi]:
                builder.records.append(record)
            builder.write()
            ingest.ingest_session(conn, builder.path)
        assert _stamps(conn) == EXPECTED
        assert _session(conn)["bridge_owner_uuid"] == "acc-B"
        assert _session(conn)["owner_account_uuid"] == "acc-A"

    def test_subagent_turns_inherit_the_sessions_current_owner(self, builder):
        path = _two_owner(builder).write()
        builder.subagent("ag1", ["a1"], T2)
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert _stamps(conn)["a1"] == "acc-B"

    def test_a_later_incremental_bridge_moves_only_later_turns(self, builder):
        path = builder.raw(_bridge("acc-A")).turn("m1", T0).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        builder.append(_bridge("acc-B"))
        builder.append(_assistant("m2", ts=T1))
        ingest.ingest_session(conn, path)
        row = _session(conn)
        assert row["owner_account_uuid"] == "acc-A"
        assert row["bridge_owner_uuid"] == "acc-B"
        assert _stamps(conn) == {"m1": "acc-A", "m2": "acc-B"}


class TestBackfill:
    def test_sync_full_backfills_rows_ingested_before_the_column_existed(
            self, builder, projects):
        _two_owner(builder).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        # Simulate a store from before this column: no stamps, no last owner.
        conn.execute("UPDATE turns SET account_uuid = NULL")
        conn.execute("UPDATE sessions SET bridge_owner_uuid = NULL")
        conn.commit()

        ingest.sync(conn, projects, full=True)
        assert _stamps(conn) == EXPECTED
        assert _session(conn)["bridge_owner_uuid"] == "acc-B"

    def test_a_full_resync_converges_and_never_smears_the_last_owner_backwards(
            self, builder, projects):
        # `bridge_owner_uuid` is the LAST owner. A re-read from byte 0 must not
        # seed the walk with it, or the turns written before the first bridge
        # record would be stamped with an owner that did not exist yet.
        _two_owner(builder).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        ingest.sync(conn, projects, full=True)
        ingest.sync(conn, projects, full=True)
        assert _stamps(conn) == EXPECTED

    def test_an_existing_store_is_migrated_on_open(self, tmp_path):
        db = tmp_path / "old.db"
        conn = store.connect(db)
        conn.execute("ALTER TABLE turns DROP COLUMN account_uuid")
        conn.execute("ALTER TABLE sessions DROP COLUMN bridge_owner_uuid")
        conn.commit()
        conn.close()
        conn = store.connect(db)
        assert "account_uuid" in {r[1] for r in conn.execute("PRAGMA table_info(turns)")}
        assert "bridge_owner_uuid" in {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
