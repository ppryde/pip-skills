import pytest

from scripts.models import (
    Card,
    CardParseError,
    format_tokens,
    parse_tokens,
    split_frontmatter,
)


class TestTokens:
    def test_parse_plain_int(self):
        assert parse_tokens(400000) == 400000

    def test_parse_k_suffix(self):
        assert parse_tokens("400k") == 400_000

    def test_parse_decimal_m_suffix(self):
        assert parse_tokens("2.1M") == 2_100_000

    def test_parse_none(self):
        assert parse_tokens(None) is None

    def test_parse_garbage_raises(self):
        with pytest.raises(CardParseError):
            parse_tokens("lots")

    def test_format_k(self):
        assert format_tokens(310_000) == "310k"

    def test_format_m(self):
        assert format_tokens(2_100_000) == "2.1M"

    def test_format_small(self):
        assert format_tokens(950) == "950"

    def test_format_none(self):
        assert format_tokens(None) is None

    def test_round_trip(self):
        for raw in ("150k", "2.1M", "999"):
            assert format_tokens(parse_tokens(raw)) == raw


class TestSplitFrontmatter:
    def test_splits_meta_and_body(self):
        meta, body = split_frontmatter("---\nid: WF-001\n---\n\n## Goal\nHi\n")
        assert meta == {"id": "WF-001"}
        assert body.strip() == "## Goal\nHi"

    def test_missing_frontmatter_raises(self):
        with pytest.raises(CardParseError):
            split_frontmatter("## Goal\nno frontmatter here\n")

    def test_invalid_yaml_raises(self):
        with pytest.raises(CardParseError):
            split_frontmatter("---\n{ not: valid: yaml\n---\nbody\n")

    def test_non_mapping_frontmatter_raises(self):
        with pytest.raises(CardParseError):
            split_frontmatter("---\n- just\n- a list\n---\nbody\n")


SAMPLE_CARD = """---
id: WF-012
jira: PROJ-142
title: Fix auth redirect loop on SSO logout
status: in-flight
stage: impl-review
complexity: M
sprint: 2026-07-S1
branch: fix/PROJ-142-auth-redirect-loop
worktree: ../pip-skills-wt/PROJ-142
budget:
  estimate: 400k
  actual: 310k
created: 2026-07-08
updated: 2026-07-08T14:32
blocked_on: null
---

## Goal
Stop the redirect loop.

## Plan
1. Reproduce.

## Decisions

## Review log

## Progress log

## Verification
"""


class TestCardParse:
    def test_parses_all_fields(self):
        card = Card.from_text(SAMPLE_CARD)
        assert card.id == "WF-012"
        assert card.jira == "PROJ-142"
        assert card.title == "Fix auth redirect loop on SSO logout"
        assert card.status == "in-flight"
        assert card.stage == "impl-review"
        assert card.complexity == "M"
        assert card.sprint == "2026-07-S1"
        assert card.branch == "fix/PROJ-142-auth-redirect-loop"
        assert card.worktree == "../pip-skills-wt/PROJ-142"
        assert card.budget_estimate == 400_000
        assert card.budget_actual == 310_000
        assert card.created == "2026-07-08"
        assert card.updated == "2026-07-08T14:32"
        assert card.blocked_on is None
        assert card.body.startswith("## Goal")

    def test_minimal_card(self):
        card = Card.from_text("---\nid: WF-001\ntitle: T\nstatus: planned\n---\nbody\n")
        assert card.stage is None
        assert card.budget_estimate is None
        assert card.budget_actual == 0

    def test_missing_required_field_raises(self):
        with pytest.raises(CardParseError, match="title"):
            Card.from_text("---\nid: WF-001\nstatus: planned\n---\nbody\n")

    def test_bad_status_raises(self):
        with pytest.raises(CardParseError, match="status"):
            Card.from_text("---\nid: WF-001\ntitle: T\nstatus: doing\n---\nbody\n")

    def test_bad_stage_raises(self):
        with pytest.raises(CardParseError, match="stage"):
            Card.from_text(
                "---\nid: WF-001\ntitle: T\nstatus: in-flight\nstage: coding\n---\nbody\n"
            )

    def test_round_trip_is_lossless(self):
        card = Card.from_text(SAMPLE_CARD)
        again = Card.from_text(card.to_text())
        assert again == card

    def test_to_text_formats_budget_as_strings(self):
        card = Card.from_text(SAMPLE_CARD)
        assert "estimate: 400k" in card.to_text()
        assert "actual: 310k" in card.to_text()
