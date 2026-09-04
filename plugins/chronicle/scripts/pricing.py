"""API-equivalent cost of a turn, from Anthropic's first-party list prices.

Claude Code sessions on a subscription are not billed per token, so the
figure chronicle reports is *what the same calls would have cost at API list
prices* — a stable yardstick for comparing sessions, not an invoice. It is
computed at read time from the per-turn token counts (never stored), so a
price change here is reflected the moment the page reloads, with no re-sync.

Rates are USD per million tokens. Cache writes are priced by TTL: 1.25× the
input rate for the 5-minute prefix, 2× for the 1-hour one; cache reads are
0.1× input on every model except Claude Fable 5.1 and Claude Mythos 5.1,
whose reads are $0.25 (0.025× — a quarter of Claude Fable 5's cache-read
rate; whether Claude Mythos 5.1 truly shares Claude Fable 5.1's rate was
still open when this table was last checked, so it is assumed here).
``PRICING_AS_OF`` is the date these were last checked against the pricing
page — if a model is missing, its turns are counted as *unpriced* rather than
guessed, and the report says how many.
"""
from __future__ import annotations

PRICING_AS_OF = "2026-06-24"

# model id (or id prefix — see ``rates_for``) -> USD per MTok
_RATES: dict[str, dict[str, float]] = {
    "claude-fable-5-1":  {"input": 10.0, "output": 50.0, "cache_read": 0.25},
    "claude-mythos-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25},
    "claude-fable-5":    {"input": 10.0, "output": 50.0, "cache_read": 1.00},
    "claude-mythos-5":   {"input": 10.0, "output": 50.0, "cache_read": 1.00},
    "claude-opus-5":     {"input": 5.0,  "output": 25.0, "cache_read": 0.50},
    "claude-opus-4-8":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50},
    "claude-opus-4-7":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50},
    "claude-opus-4-6":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50},
    "claude-sonnet-5":   {"input": 2.0,  "output": 10.0, "cache_read": 0.20},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_read": 0.30},
    "claude-haiku-4-5":  {"input": 1.0,  "output": 5.0,  "cache_read": 0.10},
}
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0

_MTOK = 1_000_000


def rates_for(model: str | None) -> dict[str, float] | None:
    """Rates for a model id, or None when it is not in the table.

    Exact id first; otherwise the longest table key the id extends on a
    ``-`` boundary, so a dated snapshot (``claude-haiku-4-5-20251001``)
    resolves to its family and ``claude-fable-5-1`` never matches
    ``claude-fable-5``'s row.
    """
    if not model:
        return None
    if model in _RATES:
        return _RATES[model]
    best: str | None = None
    for key in _RATES:
        if model.startswith(key + "-") and (best is None or len(key) > len(best)):
            best = key
    return _RATES[best] if best else None


def turn_cost(model: str | None, *, input_tokens: int = 0, cache_read_tokens: int = 0,
              cache_creation_tokens: int = 0, cache_5m_tokens: int = 0,
              cache_1h_tokens: int = 0, output_tokens: int = 0) -> float | None:
    """USD for one API call at list prices; None when the model is unpriced.

    ``output_tokens`` already includes thinking (the API bills them as
    output). Cache-creation tokens are billed by TTL from the 5m/1h split;
    any creation the split does not account for (a transcript written before
    the API reported the split) is billed at the 5-minute rate, the default.
    """
    rates = rates_for(model)
    if rates is None:
        return None
    split = cache_5m_tokens + cache_1h_tokens
    unsplit = max(0, cache_creation_tokens - split)
    write_5m = cache_5m_tokens + unsplit
    usd = (
        input_tokens * rates["input"]
        + cache_read_tokens * rates["cache_read"]
        + write_5m * rates["input"] * CACHE_WRITE_5M_MULTIPLIER
        + cache_1h_tokens * rates["input"] * CACHE_WRITE_1H_MULTIPLIER
        + output_tokens * rates["output"]
    )
    return usd / _MTOK
