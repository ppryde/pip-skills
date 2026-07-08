"""Card data model: frontmatter parse/serialise, token arithmetic, mutations."""
from __future__ import annotations

import re

import yaml

STATUSES = {"planned", "in-flight", "blocked", "done", "abandoned"}
STAGES = [
    "bootstrap",
    "planning",
    "plan-review",
    "implementation",
    "impl-review",
    "verification",
    "awaiting-merge",
]

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_TOKENS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kM])?")


class CardParseError(ValueError):
    """A card file that cannot be parsed or fails validation."""


def parse_tokens(value: str | int | float | None) -> int | None:
    """'400k' -> 400_000, '2.1M' -> 2_100_000, 999 -> 999. None passes through."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = _TOKENS_RE.fullmatch(str(value).strip())
    if match is None:
        raise CardParseError(f"unparseable token count: {value!r}")
    multiplier = {"k": 1_000, "M": 1_000_000}.get(match.group(2) or "", 1)
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


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown document into (frontmatter mapping, body)."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise CardParseError("no frontmatter block found")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise CardParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise CardParseError("frontmatter is not a mapping")
    return meta, match.group(2)
