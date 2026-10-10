"""Token-count parsing and formatting. Stdlib only, so the PreToolUse hook
(``hookfast.py``) can format a tripwire message without importing the card
model (and with it PyYAML). ``scripts.models`` re-exports both functions."""
from __future__ import annotations

import re


class CardParseError(ValueError):
    """A card file that cannot be parsed or fails validation (defined here so
    ``parse_tokens`` can raise it without importing the card model;
    ``scripts.models`` re-exports it)."""


_TOKENS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kKmM])?")


def parse_tokens(value: str | int | float | None) -> int | None:
    """'400k' -> 400_000, '2.1M' -> 2_100_000, 999 -> 999. None passes through.

    The suffix is case-insensitive ('1.5m' == '1.5M'), matching the dashboard's
    `parseTokens` in AttributesEditor.tsx.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = _TOKENS_RE.fullmatch(str(value).strip())
    if match is None:
        raise CardParseError(f"unparseable token count: {value!r}")
    multiplier = {"k": 1_000, "m": 1_000_000}.get((match.group(2) or "").lower(), 1)
    return int(float(match.group(1)) * multiplier)


def format_tokens(n: int | None) -> str | None:
    """400_000 -> '400k', 2_100_000 -> '2.1M', 999 -> '999'. None passes through."""
    if n is None:
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1_000:
        return f"{n / 1_000:g}k"
    return str(n)
