from scripts import pricing


class TestRatesFor:
    def test_exact_and_dated_snapshot(self):
        assert pricing.rates_for("claude-opus-5")["input"] == 5.0
        # A dated snapshot resolves to its family.
        assert pricing.rates_for("claude-haiku-4-5-20251001")["output"] == 5.0

    def test_longest_prefix_wins(self):
        # fable-5-1 must not fall through to fable-5's (dearer) cache-read row.
        assert pricing.rates_for("claude-fable-5-1")["cache_read"] == 0.25
        assert pricing.rates_for("claude-fable-5")["cache_read"] == 1.0
        # "claude-fable-50" is not "claude-fable-5-..." — no boundary match.
        assert pricing.rates_for("claude-fable-50") is None

    def test_unknown(self):
        assert pricing.rates_for(None) is None
        assert pricing.rates_for("") is None
        assert pricing.rates_for("gpt-9") is None


class TestTurnCost:
    def test_prices_each_bucket(self):
        usd = pricing.turn_cost(
            "claude-opus-5", input_tokens=1_000_000, cache_read_tokens=1_000_000,
            cache_creation_tokens=2_000_000, cache_5m_tokens=1_000_000,
            cache_1h_tokens=1_000_000, output_tokens=1_000_000,
        )
        # 5 + 0.5 + 5*1.25 + 5*2 + 25
        assert round(usd, 6) == 46.75

    def test_unsplit_cache_creation_bills_at_5m(self):
        # No TTL split recorded: the whole creation figure is 5-minute cache.
        assert round(pricing.turn_cost("claude-sonnet-5", cache_creation_tokens=1_000_000), 6) == 2.5
        # A partial split: the remainder is 5-minute too.
        usd = pricing.turn_cost("claude-sonnet-5", cache_creation_tokens=1_000_000,
                                cache_1h_tokens=400_000)
        assert round(usd, 6) == round(0.4 * 4.0 + 0.6 * 2.5, 6)

    def test_unknown_model_is_none_not_zero(self):
        assert pricing.turn_cost("unknown-model", output_tokens=10) is None
        assert pricing.turn_cost(None, output_tokens=10) is None

    def test_zero_tokens(self):
        assert pricing.turn_cost("claude-opus-5") == 0.0


class TestOpus55:
    """Claude Opus 5.5 is cheaper than Opus 5 and has its own row: without one
    it prefix-matched `claude-opus-5` and was billed $5/$25 instead of $4/$20."""

    def test_exact_row_beats_prefix(self):
        assert pricing.rates_for("claude-opus-5-5") == {
            "input": 4.0, "output": 20.0, "cache_read": 0.20}

    def test_dated_snapshot_resolves_to_5_5_and_opus_5_is_untouched(self):
        assert pricing.rates_for("claude-opus-5-5-20260901") == pricing.rates_for("claude-opus-5-5")
        assert pricing.rates_for("claude-opus-5") == {
            "input": 5.0, "output": 25.0, "cache_read": 0.50}
        assert pricing.rates_for("claude-opus-5-20260101")["input"] == 5.0

    def test_cache_write_multipliers(self):
        # 5m write = 1.25x input = $5; 1h write = 2x input = $8.
        assert round(pricing.turn_cost("claude-opus-5-5", cache_5m_tokens=1_000_000,
                                       cache_creation_tokens=1_000_000), 6) == 5.0
        assert round(pricing.turn_cost("claude-opus-5-5", cache_1h_tokens=1_000_000,
                                       cache_creation_tokens=1_000_000), 6) == 8.0

    def test_turn_cost_example(self):
        usd = pricing.turn_cost(
            "claude-opus-5-5", input_tokens=1_000_000, cache_read_tokens=1_000_000,
            cache_creation_tokens=2_000_000, cache_5m_tokens=1_000_000,
            cache_1h_tokens=1_000_000, output_tokens=1_000_000,
        )
        # 4 + 0.2 + 5 + 8 + 20
        assert round(usd, 6) == 37.2

    def test_pricing_as_of(self):
        assert pricing.PRICING_AS_OF == "2026-09-25"
