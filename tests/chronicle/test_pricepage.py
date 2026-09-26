"""The pricing-page parser: one interface over markdown and HTML tables."""
from pathlib import Path

import pytest
from scripts import pricepage
from scripts.pricepage import PagePrice, model_id, parse_pricing

FIXTURES = Path(__file__).parent / "fixtures"


def md():
    return (FIXTURES / "pricing_page.md").read_text()


def html():
    return (FIXTURES / "pricing_page.html").read_text()


class TestModelId:
    @pytest.mark.parametrize("name, expected", [
        ("Claude Opus 5.5", "claude-opus-5-5"),
        ("Claude Opus 5", "claude-opus-5"),
        ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
        ("Claude Haiku 4.5", "claude-haiku-4-5"),
        ("Claude Fable 5.1", "claude-fable-5-1"),
        ("Claude Mythos 5.1", "claude-mythos-5-1"),
        ("Claude Opus 4", "claude-opus-4"),
        ("claude   opus  4.1", "claude-opus-4-1"),
        # Claude 3 kept the version BEFORE the family in its ids.
        ("Claude Haiku 3.5", "claude-3-5-haiku"),
        ("Claude Sonnet 3.7", "claude-3-7-sonnet"),
        ("Claude Opus 3", "claude-3-opus"),
        ("Claude 3.5 Haiku", "claude-3-5-haiku"),
        ("Claude Aurora 6", "claude-aurora-6"),
    ])
    def test_maps_display_names(self, name, expected):
        assert model_id(name) == expected

    @pytest.mark.parametrize("name", ["", "Claude", "Claude Code", "GPT 5", "Claude Opus", "Batch input"])
    def test_rejects_what_is_not_a_model(self, name):
        assert model_id(name) is None


class TestParseMarkdown:
    def test_parses_the_model_pricing_table(self):
        res = parse_pricing(md())
        assert res.error is None
        assert set(res.prices) == {
            "claude-fable-5-1", "claude-mythos-5-1", "claude-opus-5-5", "claude-opus-5",
            "claude-opus-4-1", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5",
            "claude-3-5-haiku"}
        assert res.prices["claude-opus-5-5"] == PagePrice(4.0, 20.0, 0.20, 5.0, 8.0)
        assert res.prices["claude-fable-5-1"].cache_read == 0.25

    def test_footnote_markers_do_not_leak_into_numbers(self):
        # "$0.25 / MTok<sup>1</sup>" and "$2 / MTok<sup>3</sup>"
        res = parse_pricing(md())
        assert res.prices["claude-fable-5-1"] == PagePrice(10.0, 50.0, 0.25, 12.5, 20.0)
        assert res.prices["claude-sonnet-5"] == PagePrice(2.0, 10.0, 0.20, 2.5, 4.0)

    def test_retired_rows_are_parsed_too(self):
        res = parse_pricing(md())
        assert res.prices["claude-opus-4-1"] == PagePrice(15.0, 75.0, 1.5, 18.75, 30.0)
        assert res.prices["claude-3-5-haiku"] == PagePrice(0.8, 4.0, 0.08, 1.0, 1.6)

    def test_only_the_first_matching_table_is_read(self):
        # The batch table below lists "Claude Opus 5" at half price; it has no cache column.
        assert parse_pricing(md()).prices["claude-opus-5"].input == 5.0


class TestParseHtml:
    def test_html_and_markdown_give_the_same_rows(self):
        h, m = parse_pricing(html()), parse_pricing(md())
        assert h.error is None
        assert set(h.prices) == {"claude-opus-5", "claude-sonnet-5", "claude-opus-4-1", "claude-3-5-haiku"}
        for model, price in h.prices.items():
            assert m.prices[model] == price

    def test_link_and_sup_text_is_ignored(self):
        h = parse_pricing(html())
        assert h.prices["claude-sonnet-5"] == PagePrice(2.0, 10.0, 0.20, 2.5, 4.0)
        assert "claude-opus-4-1" in h.prices


class TestOlderLayouts:
    def test_page_without_ttl_split_columns_has_no_cache_write_prices(self):
        text = (
            "| Model | Input | Cache Writes | Cache Hits & Refreshes | Output |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Claude Sonnet 4 | $3 / MTok | $3.75 / MTok | $0.30 / MTok | $15 / MTok |\n")
        res = parse_pricing(text)
        # A single "Cache Writes" column is the 5-minute price (the only TTL then).
        assert res.prices["claude-sonnet-4"] == PagePrice(3.0, 15.0, 0.30, 3.75, None)

    def test_page_with_no_cache_write_columns_at_all(self):
        text = (
            "| Model | Input | Cache Read | Output |\n| --- | --- | --- | --- |\n"
            "| Claude Opus 4 | $15 / MTok | $1.50 / MTok | $75 / MTok |\n")
        assert parse_pricing(text).prices["claude-opus-4"] == PagePrice(15.0, 75.0, 1.5, None, None)


class TestSurprises:
    """Any layout surprise is an error carrying no prices: nothing to write."""

    def test_no_tables(self):
        res = parse_pricing("just prose\n\nno tables here")
        assert res.prices == {} and res.error

    def test_empty_and_garbage(self):
        assert parse_pricing("").error
        assert parse_pricing("<html><body><p>Access denied</p></body></html>").error
        assert parse_pricing("\x00\x01 binary \xff").error

    def test_missing_required_column(self):
        text = "| Model | Base input tokens |\n| --- | --- |\n| Claude Opus 5 | $5 / MTok |\n"
        res = parse_pricing(text)
        assert res.prices == {} and "column" in res.error

    def test_zero_models_parsed(self):
        text = ("| Model | Input | Cache Read | Output |\n| --- | --- | --- | --- |\n"
                "| Enterprise | Contact us | Contact us | Contact us |\n")
        res = parse_pricing(text)
        assert res.prices == {} and res.error

    def test_a_row_with_a_bad_cell_is_skipped_and_reported_not_guessed(self):
        text = ("| Model | Input | Cache Read | Output |\n| --- | --- | --- | --- |\n"
                "| Claude Opus 5 | $5 / MTok | $0.50 / MTok | $25 / MTok |\n"
                "| Claude Sonnet 5 | TBD | $0.20 / MTok | $10 / MTok |\n")
        res = parse_pricing(text)
        assert res.error is None
        assert set(res.prices) == {"claude-opus-5"}
        assert any("Sonnet 5" in s for s in res.skipped)

    def test_conflicting_duplicate_model_is_an_error(self):
        text = ("| Model | Input | Cache Read | Output |\n| --- | --- | --- | --- |\n"
                "| Claude Opus 5 | $5 / MTok | $0.50 / MTok | $25 / MTok |\n"
                "| Claude Opus 5 | $9 / MTok | $0.90 / MTok | $45 / MTok |\n")
        res = parse_pricing(text)
        assert res.prices == {} and "twice" in res.error

    def test_non_positive_price_is_a_bad_row(self):
        text = ("| Model | Input | Cache Read | Output |\n| --- | --- | --- | --- |\n"
                "| Claude Opus 5 | $0 / MTok | $0.50 / MTok | $25 / MTok |\n")
        assert parse_pricing(text).error


class TestFetch:
    def test_fetch_error_on_bad_scheme(self):
        with pytest.raises(pricepage.FetchError):
            pricepage.fetch_text("file:///etc/passwd", timeout=1)

    def test_fetch_error_on_unreachable_host(self, monkeypatch):
        import urllib.request

        def boom(*a, **k):
            raise OSError("no network in tests")
        monkeypatch.setattr(urllib.request, "urlopen", boom)
        with pytest.raises(pricepage.FetchError):
            pricepage.fetch_text("https://example.test/x", timeout=1)
