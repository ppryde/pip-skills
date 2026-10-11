import pytest

from scripts import db
from scripts.knowledge import (
    Fact,
    FactParseError,
    generate_knowledge_index,
    is_stale,
    load_fact,
    load_facts,
    load_retired,
    mint_fact_id,
    refresh_stale,
    retire_fact,
    save_fact,
)


def make_fact(fact_id: str = "KB-001", **overrides: object) -> Fact:
    fields = dict(
        id=fact_id,
        statement="The auth fixtures share a DB schema",
        tags=["testing", "auth"],
        source="WF-012",
        created="2026-07-09",
        verified="2026-07-09",
        status="active",
        body="Fuller story.",
    )
    fields.update(overrides)
    return Fact(**fields)  # type: ignore[arg-type]


class TestFactParse:
    def test_round_trip(self):
        fact = make_fact()
        parsed = Fact.from_text(fact.to_text())
        assert parsed == fact

    def test_missing_statement_raises(self):
        with pytest.raises(FactParseError):
            Fact.from_text("---\nid: KB-001\nstatus: active\n---\nx")

    def test_bad_status_raises(self):
        with pytest.raises(FactParseError):
            Fact.from_text(
                "---\nid: KB-001\nstatement: x\nstatus: bogus\n---\ny"
            )

    def test_scalar_tags_not_exploded(self):
        text = (
            "---\nid: KB-002\nstatement: x\nstatus: active\n"
            "tags: testing\n---\n\nbody\n"
        )
        assert Fact.from_text(text).tags == ["testing"]

    def test_absent_tags_default_empty(self):
        text = "---\nid: KB-003\nstatement: x\nstatus: active\n---\n\nbody\n"
        assert Fact.from_text(text).tags == []


class TestStaleness:
    def test_fresh_is_not_stale(self):
        assert is_stale("2026-07-09", "2026-07-10") is False

    def test_old_is_stale(self):
        assert is_stale("2026-01-01", "2026-07-09") is True

    def test_exactly_90_days_not_stale(self):
        assert is_stale("2026-01-01", "2026-04-01") is False  # 90 days exactly

    def test_unparseable_is_not_stale(self):
        assert is_stale("", "2026-07-09") is False
        assert is_stale("garbage", "2026-07-09") is False

    def test_effective_status_flags_stale_active(self):
        fact = make_fact(status="active", verified="2026-01-01")
        assert fact.effective_status("2026-07-09") == "stale"

    def test_effective_status_leaves_retired(self):
        fact = make_fact(status="retired", verified="2026-01-01")
        assert fact.effective_status("2026-07-09") == "retired"


class TestStoreOps:
    def test_mint_first_id(self, board_conn):
        assert mint_fact_id(board_conn) == "KB-001"

    def test_mint_skips_facts_and_retired(self, board_conn):
        save_fact(board_conn, make_fact("KB-004"))
        retire_fact(board_conn, make_fact("KB-007"))
        assert mint_fact_id(board_conn) == "KB-008"

    def test_save_and_load(self, board_conn):
        save_fact(board_conn, make_fact("KB-001", statement="Serial tests only"))
        assert load_fact(board_conn, "KB-001").statement == "Serial tests only"

    def test_load_missing_raises(self, board_conn):
        with pytest.raises(FileNotFoundError):
            load_fact(board_conn, "KB-999")

    def test_round_trips_every_field(self, board_conn):
        fact = make_fact("KB-001", superseded_by="KB-002", tags=["a", "b"])
        save_fact(board_conn, fact)
        assert load_fact(board_conn, "KB-001") == fact

    def test_load_facts_sorted_and_reads_never_mutate(self, board_conn, tmp_path):
        save_fact(board_conn, make_fact("KB-002", statement="B"))
        save_fact(board_conn, make_fact("KB-001", statement="A"))
        facts, quarantined = load_facts(board_conn)
        assert [f.id for f in facts] == ["KB-001", "KB-002"]
        assert quarantined == []
        assert not any(tmp_path.rglob("corrupt/*"))

    def test_retire_moves_the_row_out_of_the_live_set(self, board_conn):
        save_fact(board_conn, make_fact("KB-001"))
        retire_fact(board_conn, make_fact("KB-001", superseded_by="KB-002"))
        assert load_facts(board_conn)[0] == []
        retired = load_retired(board_conn)
        assert [f.id for f in retired] == ["KB-001"]
        assert retired[0].superseded_by == "KB-002"
        assert retired[0].status == "retired"
        with pytest.raises(FileNotFoundError):  # a retired fact is not "live"
            load_fact(board_conn, "KB-001")

    def test_concurrent_mints_cannot_collide(self, tmp_path):
        """Mint + insert under one writer lock: two connections racing the same
        id both succeed with distinct ids (the file store's glob-then-write raced)."""
        a = db.connect(tmp_path, migrate=False)
        b = db.connect(tmp_path, migrate=False)
        ids = []
        for conn in (a, b, a, b):
            with db.txn(conn):
                fid = mint_fact_id(conn)
                save_fact(conn, make_fact(fid, statement=f"s{len(ids)}"))
                ids.append(fid)
        assert ids == ["KB-001", "KB-002", "KB-003", "KB-004"]


class TestIndex:
    def test_generate_lists_active_and_stale_and_counts_retired(self):
        active = make_fact("KB-001", statement="Alpha truth", status="active")
        stale = make_fact("KB-002", statement="Beta truth", status="stale")
        retired = make_fact("KB-009", statement="Gamma truth", status="retired")
        out = generate_knowledge_index([active, stale], [retired], "2026-07-09")
        assert "KB-001" in out and "Alpha truth" in out
        assert "## Stale" in out and "KB-002" in out and "Beta truth" in out
        assert "## Retired: 1" in out
        assert "KB-009" not in out  # retired ids/bodies stay out of the index
        assert "Gamma truth" not in out

    def test_refresh_persists_stale_flip(self, board_conn):
        save_fact(board_conn, make_fact("KB-001", status="active", verified="2026-01-01"))
        assert refresh_stale(board_conn, "2026-07-09") == 1
        assert load_facts(board_conn)[0][0].status == "stale"

    def test_refresh_leaves_fresh_active(self, board_conn):
        save_fact(board_conn, make_fact("KB-001", status="active", verified="2026-07-08"))
        assert refresh_stale(board_conn, "2026-07-09") == 0
        assert load_facts(board_conn)[0][0].status == "active"
