"""API-equivalent cost of a turn, from Anthropic's first-party list prices.

Claude Code sessions on a subscription are not billed per token, so the
figure chronicle reports is *what the same calls would have cost at API list
prices* — a stable yardstick for comparing sessions, not an invoice. It is
computed at read time from the per-turn token counts (never stored), so a
change to a rate is reflected the moment the page reloads, with no re-sync.

Where the rates come from: the store's ``price_history`` table
(``scripts.ratebook`` — rates WITH HISTORY, so a turn is priced at the rate in
force when it ran, refreshed from the pricing page by ``scripts.pricerefresh``).
``_RATES`` below is the *seed and the offline fallback*: it is what an empty or
not-yet-migrated store, or a model the table has never heard of, is priced
with, and what ``chronicle pricing seed`` writes into the table. It is only
hand-maintained as a last resort now — ``PRICING_AS_OF`` is the date it was
last checked against the pricing page.

Rates are USD per million tokens. Cache writes are priced by TTL: 1.25× the
input rate for the 5-minute prefix, 2× for the 1-hour one (the table stores the
page's own dollar figures and falls back to these multipliers when a source
lacks them); cache reads are 0.1× input on every model except Claude Fable 5.1
and Claude Mythos 5.1, whose reads are $0.25 (0.025× — a quarter of Claude
Fable 5's cache-read rate; whether Claude Mythos 5.1 truly shares Claude Fable
5.1's rate was still open when this table was last checked, so it is assumed
here), and Claude Opus 5.5, whose reads are $0.20 (0.05× its $4 input rate).
If a model is missing everywhere, its turns are counted as *unpriced* rather
than guessed, and the report says how many.
"""
from __future__ import annotations

from typing import Any

PRICING_AS_OF = "2026-09-25"

# model id (or id prefix — see ``rates_for``) -> USD per MTok
_RATES: dict[str, dict[str, float]] = {
    "claude-fable-5-1":  {"input": 10.0, "output": 50.0, "cache_read": 0.25},
    "claude-mythos-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25},
    "claude-fable-5":    {"input": 10.0, "output": 50.0, "cache_read": 1.00},
    "claude-mythos-5":   {"input": 10.0, "output": 50.0, "cache_read": 1.00},
    "claude-opus-5-5":   {"input": 4.0,  "output": 20.0, "cache_read": 0.20},
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
    """Built-in rates for a model id, or None when it is not in the table.

    Exact id first; otherwise the longest table key the id extends on a
    ``-`` boundary, so a dated snapshot (``claude-haiku-4-5-20251001``)
    resolves to its family and ``claude-fable-5-1`` never matches
    ``claude-fable-5``'s row. (``ratebook.RateBook.rates_for`` has the same
    semantics over the store's history.)
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
              cache_1h_tokens: int = 0, output_tokens: int = 0,
              book: Any = None, ts: float | None = None) -> float | None:
    """USD for one API call at list prices; None when the model is unpriced.

    With a ``book`` (a ``ratebook.RateBook``) the model is priced at the rate in
    force at ``ts``; without one, at the built-in table.

    ``output_tokens`` already includes thinking (the API bills them as
    output). Cache-creation tokens are billed by TTL from the 5m/1h split;
    any creation the split does not account for (a transcript written before
    the API reported the split) is billed at the 5-minute rate, the default.
    """
    rates = rates_for(model) if book is None else book.rates_for(model, ts)
    if rates is None:
        return None
    split = cache_5m_tokens + cache_1h_tokens
    unsplit = max(0, cache_creation_tokens - split)
    write_5m = cache_5m_tokens + unsplit
    w5 = rates.get("cache_write_5m")
    w1 = rates.get("cache_write_1h")
    usd = (
        input_tokens * rates["input"]
        + cache_read_tokens * rates["cache_read"]
        + (write_5m * rates["input"] * CACHE_WRITE_5M_MULTIPLIER if w5 is None else write_5m * w5)
        + (cache_1h_tokens * rates["input"] * CACHE_WRITE_1H_MULTIPLIER
           if w1 is None else cache_1h_tokens * w1)
        + output_tokens * rates["output"]
    )
    return usd / _MTOK
