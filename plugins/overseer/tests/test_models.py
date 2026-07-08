import pytest

from scripts.models import (
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
