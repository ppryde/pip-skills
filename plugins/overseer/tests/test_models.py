import pytest

from scripts.models import (
    Card,
    CardParseError,
    append_to_section,
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

    def test_non_mapping_budget_raises(self):
        with pytest.raises(CardParseError, match="budget"):
            Card.from_text("---\nid: W-1\ntitle: T\nstatus: planned\nbudget: TBD\n---\nx")

    def test_round_trip_is_lossless(self):
        card = Card.from_text(SAMPLE_CARD)
        again = Card.from_text(card.to_text())
        assert again == card

    def test_to_text_formats_budget_as_strings(self):
        card = Card.from_text(SAMPLE_CARD)
        assert "estimate: 400k" in card.to_text()
        assert "actual: 310k" in card.to_text()


NOW = "2026-07-08T15:00"


def make_card() -> Card:
    return Card.from_text(SAMPLE_CARD)


class TestAppendToSection:
    def test_appends_inside_section(self):
        body = "## Progress log\n- old line\n\n## Verification\nevidence"
        out = append_to_section(body, "## Progress log", "- new line")
        assert out.index("- new line") < out.index("## Verification")
        assert out.index("- old line") < out.index("- new line")

    def test_appends_to_last_section(self):
        out = append_to_section("## Progress log\n- old", "## Progress log", "- new")
        assert out.endswith("- new")

    def test_missing_section_is_created(self):
        out = append_to_section("## Goal\nhi", "## Progress log", "- new")
        assert "## Progress log\n- new" in out


class TestMutations:
    def test_set_stage(self):
        card = make_card()
        card.set_stage("verification", NOW)
        assert (card.status, card.stage, card.updated) == ("in-flight", "verification", NOW)

    def test_set_bad_stage_raises(self):
        with pytest.raises(CardParseError):
            make_card().set_stage("coding", NOW)

    def test_set_stage_clears_stale_blocked_on(self):
        card = make_card()
        card.block("user: q", NOW)
        card.set_stage("verification", NOW)
        assert card.blocked_on is None

    def test_block_preserves_stage(self):
        card = make_card()
        card.block("user: scope question", NOW)
        assert card.status == "blocked"
        assert card.blocked_on == "user: scope question"
        assert card.stage == "impl-review"

    def test_unblock_returns_to_in_flight(self):
        card = make_card()
        card.block("user: q", NOW)
        card.unblock(NOW)
        assert card.status == "in-flight"
        assert card.blocked_on is None

    def test_unblock_without_stage_returns_to_planned(self):
        card = Card.from_text("---\nid: W-1\ntitle: T\nstatus: planned\n---\nx")
        card.block("card: WF-011", NOW)
        card.unblock(NOW)
        assert card.status == "planned"

    def test_complete_clears_stage(self):
        card = make_card()
        card.complete(NOW)
        assert (card.status, card.stage) == ("done", None)

    def test_abandon(self):
        card = make_card()
        card.abandon(NOW)
        assert card.status == "abandoned"

    def test_log_progress_adds_tokens_and_line(self):
        card = make_card()
        card.log_progress("impl agent: steps 1-3 done", 120_000, NOW)
        assert card.budget_actual == 430_000
        assert f"- {NOW} — impl agent: steps 1-3 done (~120k tokens)" in card.body

    def test_log_review_rounds_auto_increment(self):
        card = make_card()
        card.log_review("impl-review", 2, "found wanting — 2 findings", NOW)
        card.log_review("impl-review", 2, "approved", NOW)
        assert card.review_rounds("impl-review") == 2
        assert "### impl-review — round 2 (2 reviewers)\nVerdict: approved" in card.body

    def test_tripwire(self):
        card = make_card()
        assert card.tripwire_breached is False
        card.log_progress("big burn", 490_000, NOW)  # 310k + 490k = 800k >= 2*400k
        assert card.tripwire_breached is True

    def test_tripwire_without_estimate_never_fires(self):
        card = Card.from_text("---\nid: W-1\ntitle: T\nstatus: planned\n---\nx")
        card.log_progress("work", 10_000_000, NOW)
        assert card.tripwire_breached is False


class TestLinearAndPrFields:
    def test_linear_round_trip(self):
        card = Card.from_text(
            "---\nid: ENG-42\nlinear: ENG-42\ntitle: T\nstatus: planned\n---\nx"
        )
        assert card.linear == "ENG-42"
        assert Card.from_text(card.to_text()) == card
        assert "linear: ENG-42" in card.to_text()

    def test_pr_round_trip(self):
        card = Card.from_text(SAMPLE_CARD)
        card.pr = "https://github.com/ppryde/pip-skills/pull/22"
        again = Card.from_text(card.to_text())
        assert again.pr == card.pr

    def test_both_default_none(self):
        card = Card.from_text(SAMPLE_CARD)
        assert card.linear is None
        assert card.pr is None
