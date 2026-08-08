import pytest

from scripts.knowledge import (
    Fact,
    FactParseError,
    ensure_kb,
    find_fact_path,
    generate_knowledge_index,
    is_stale,
    knowledge_root,
    load_facts,
    load_retired,
    mint_fact_id,
    rebuild_knowledge_index,
    retire_fact_file,
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


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "knowledge"
    ensure_kb(root)
    return root


class TestStoreOps:
    def test_ensure_creates_dirs(self, tmp_path):
        root = tmp_path / "knowledge"
        ensure_kb(root)
        for sub in ("facts", "retired", "corrupt"):
            assert (root / sub).is_dir()

    def test_mint_first_id(self, kb):
        assert mint_fact_id(kb) == "KB-001"

    def test_mint_skips_facts_and_retired(self, kb):
        save_fact(kb, make_fact("KB-004"))
        retire_fact_file(kb, make_fact("KB-007", status="retired"))
        assert mint_fact_id(kb) == "KB-008"

    def test_save_and_find(self, kb):
        save_fact(kb, make_fact("KB-001", statement="Serial tests only"))
        path = find_fact_path(kb, "KB-001")
        assert path.name.startswith("KB-001-")
        assert path.parent == kb / "facts"

    def test_find_missing_raises(self, kb):
        with pytest.raises(FileNotFoundError):
            find_fact_path(kb, "KB-999")

    def test_load_facts_sorted_and_quarantines_corrupt(self, kb):
        save_fact(kb, make_fact("KB-002", statement="B"))
        save_fact(kb, make_fact("KB-001", statement="A"))
        bad = kb / "facts" / "KB-003-broken.md"
        bad.write_text("no frontmatter here")
        facts, quarantined = load_facts(kb)
        assert [f.id for f in facts] == ["KB-001", "KB-002"]
        assert quarantined == [kb / "corrupt" / "KB-003-broken.md"]
        assert not bad.exists()
        assert (kb / "corrupt" / "KB-003-broken.md").read_text() == "no frontmatter here"

    def test_retire_moves_file(self, kb):
        save_fact(kb, make_fact("KB-001"))
        fact = make_fact("KB-001", status="retired", superseded_by="KB-002")
        retire_fact_file(kb, fact)
        assert not list((kb / "facts").glob("KB-001-*"))
        retired = load_retired(kb)
        assert [f.id for f in retired] == ["KB-001"]
        assert retired[0].superseded_by == "KB-002"


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

    def test_rebuild_persists_stale_flip(self, tmp_path):
        kb = knowledge_root(tmp_path)
        ensure_kb(kb)
        save_fact(kb, make_fact("KB-001", status="active", verified="2026-01-01"))
        quarantined = rebuild_knowledge_index(tmp_path, "2026-07-09")
        assert quarantined == []
        reloaded = load_facts(kb)[0][0]
        assert reloaded.status == "stale"
        assert (kb / "knowledge.md").exists()

    def test_rebuild_leaves_fresh_active(self, tmp_path):
        kb = knowledge_root(tmp_path)
        ensure_kb(kb)
        save_fact(kb, make_fact("KB-001", status="active", verified="2026-07-08"))
        rebuild_knowledge_index(tmp_path, "2026-07-09")
        assert load_facts(kb)[0][0].status == "active"
