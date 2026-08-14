"""Load .review-panel/config.yml and resolve a profile (or an ad-hoc
reviewer list) into a ResolvedReview the orchestrator can execute."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_STRICTNESS = {"strict", "pragmatic", "aspirational"}
VALID_SCOPE = {"changed", "full"}
VALID_OUTPUT = {"report", "inline", "interactive"}
DEFAULT_STRATEGY = "committee"
DEFAULT_SCOPE = "changed"
DEFAULT_OUTPUT = "report"
DEFAULT_STRICTNESS = "pragmatic"


class ConfigError(Exception):
    """Raised on malformed config or an impossible resolution request."""


@dataclass(frozen=True)
class ReviewerRef:
    key: str
    source: str  # "builtin" | "clone"
    name: str
    strictness: str


@dataclass(frozen=True)
class ResolvedReview:
    strategy: str
    scope: str
    targets: tuple[str, ...]
    reviewers: tuple[ReviewerRef, ...]
    context: tuple[str, ...]
    output: str


def load_config(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    try:
        data = yaml.safe_load(Path(path).read_text()) or {}
    except yaml.YAMLError as exc:  # noqa: BLE001 - re-raise as our type
        raise ConfigError(f"malformed config: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    return data


def parse_reviewer_key(key: str, strictness: str) -> ReviewerRef:
    if strictness not in VALID_STRICTNESS:
        raise ConfigError(
            f"invalid strictness {strictness!r} for reviewer {key!r}; "
            f"expected one of {sorted(VALID_STRICTNESS)}"
        )
    if key.startswith("clone:"):
        alias = key[len("clone:"):]
        if not alias:
            raise ConfigError("clone reviewer key needs an alias, e.g. clone:danvk")
        return ReviewerRef(key, "clone", alias, strictness)
    return ReviewerRef(key, "builtin", key, strictness)


def _reviewers(raw: dict) -> tuple[ReviewerRef, ...]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("a profile needs a non-empty 'reviewers' mapping")
    return tuple(parse_reviewer_key(k, str(v)) for k, v in raw.items())


def resolve_profile(config: dict, profile: str | None) -> ResolvedReview:
    defaults = config.get("defaults", {}) or {}
    profiles = config.get("profiles", {}) or {}
    name = profile if profile is not None else defaults.get("profile")
    if name is None:
        raise ConfigError("no profile given and no defaults.profile set")
    if name not in profiles:
        raise ConfigError(f"unknown profile {name!r}; have {sorted(profiles)}")
    spec = profiles[name] or {}
    strategy = spec.get("strategy", defaults.get("strategy", DEFAULT_STRATEGY))
    scope = spec.get("scope", defaults.get("scope", DEFAULT_SCOPE))
    if scope not in VALID_SCOPE:
        raise ConfigError(f"invalid scope {scope!r}; expected {sorted(VALID_SCOPE)}")
    output = (config.get("output", {}) or {}).get("default", DEFAULT_OUTPUT)
    if output not in VALID_OUTPUT:
        raise ConfigError(f"invalid output {output!r}; expected {sorted(VALID_OUTPUT)}")
    return ResolvedReview(
        strategy=strategy,
        scope=scope,
        targets=tuple(spec.get("targets", []) or []),
        reviewers=_reviewers(spec.get("reviewers", {})),
        context=tuple(spec.get("context", []) or []),
        output=output,
    )


def resolve_adhoc(config: dict, reviewer_keys: list[str]) -> ResolvedReview:
    defaults = config.get("defaults", {}) or {}
    if not reviewer_keys:
        raise ConfigError("ad-hoc review needs at least one reviewer")
    return ResolvedReview(
        strategy=defaults.get("strategy", DEFAULT_STRATEGY),
        scope=defaults.get("scope", DEFAULT_SCOPE),
        targets=(),
        reviewers=tuple(parse_reviewer_key(k, DEFAULT_STRICTNESS) for k in reviewer_keys),
        context=(),
        output=(config.get("output", {}) or {}).get("default", DEFAULT_OUTPUT),
    )
