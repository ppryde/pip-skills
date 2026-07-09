import pytest

from scripts.knowledge import Fact, FactParseError, is_stale


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
