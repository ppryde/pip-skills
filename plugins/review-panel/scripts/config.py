"""Load .review-panel/config.yml and resolve a profile (or an ad-hoc
reviewer list) into a ResolvedReview the orchestrator can execute."""
from __future__ import annotations

import re
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
DEFAULT_OUTPUT_FILE = ".review-panel/last-review.md"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
    output_file: str


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
    if not isinstance(key, str):
        raise ConfigError(f"reviewer key must be a string, got {key!r}")
    if key.startswith("clone:"):
        alias = key[len("clone:"):]
        if not alias:
            raise ConfigError("clone reviewer key needs an alias, e.g. clone:danvk")
        if not _NAME_RE.fullmatch(alias) or ".." in alias:
            raise ConfigError(f"invalid clone alias {alias!r}")
        return ReviewerRef(key, "clone", alias, strictness)
    if not _NAME_RE.fullmatch(key) or ".." in key:
        raise ConfigError(f"invalid reviewer name {key!r}")
    return ReviewerRef(key, "builtin", key, strictness)


def _as_tuple(value, what: str) -> tuple[str, ...]:
    """A list of strings; a lone string is one item, anything else is refused."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ConfigError(f"{what} must be a string or a list of strings, got {value!r}")


def _check_relative(path: str, what: str) -> str:
    """Refuse absolute, ~-prefixed or parent-escaping paths."""
    parts = path.replace("\\", "/").split("/")
    if path.startswith(("/", "~")) or ".." in parts or re.match(r"^[A-Za-z]:", path):
        raise ConfigError(f"{what} must be a relative path inside the repo, got {path!r}")
    return path


def _output_settings(config: dict) -> tuple[str, str]:
    out = config.get("output", {}) or {}
    if not isinstance(out, dict):
        raise ConfigError("'output' must be a mapping")
    output = out.get("default", DEFAULT_OUTPUT)
    if output not in VALID_OUTPUT:
        raise ConfigError(f"invalid output {output!r}; expected {sorted(VALID_OUTPUT)}")
    raw_file = out.get("file")
    output_file = _check_relative(
        DEFAULT_OUTPUT_FILE if raw_file is None else str(raw_file), "output.file"
    )
    return output, output_file


def _strictness_value(key, value) -> str:
    if not isinstance(value, str):
        raise ConfigError(
            f"strictness for reviewer {key!r} must be one of {sorted(VALID_STRICTNESS)}, "
            f"got {value!r}"
        )
    return value


def _reviewers(raw: dict) -> tuple[ReviewerRef, ...]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("a profile needs a non-empty 'reviewers' mapping")
    return tuple(parse_reviewer_key(k, _strictness_value(k, v)) for k, v in raw.items())


def resolve_profile(config: dict, profile: str | None) -> ResolvedReview:
    defaults = config.get("defaults", {}) or {}
    profiles = config.get("profiles", {}) or {}
    name = profile if profile is not None else defaults.get("profile")
    if name is None:
        raise ConfigError("no profile given and no defaults.profile set")
    if name not in profiles:
        raise ConfigError(f"unknown profile {name!r}; have {sorted(profiles)}")
    spec = profiles[name] or {}
    if not isinstance(spec, dict):
        raise ConfigError(f"profile {name!r} must be a mapping")
    strategy = spec.get("strategy", defaults.get("strategy", DEFAULT_STRATEGY))
    scope = spec.get("scope", defaults.get("scope", DEFAULT_SCOPE))
    if scope not in VALID_SCOPE:
        raise ConfigError(f"invalid scope {scope!r}; expected {sorted(VALID_SCOPE)}")
    output, output_file = _output_settings(config)
    return ResolvedReview(
        strategy=strategy,
        scope=scope,
        targets=_as_tuple(spec.get("targets"), "targets"),
        reviewers=_reviewers(spec.get("reviewers", {})),
        context=tuple(_check_relative(c, "context entry")
                      for c in _as_tuple(spec.get("context"), "context")),
        output=output,
        output_file=output_file,
    )


def resolve_adhoc(config: dict, reviewer_keys: list[str]) -> ResolvedReview:
    defaults = config.get("defaults", {}) or {}
    if not reviewer_keys:
        raise ConfigError("ad-hoc review needs at least one reviewer")
    output, output_file = _output_settings(config)
    return ResolvedReview(
        strategy=defaults.get("strategy", DEFAULT_STRATEGY),
        scope=defaults.get("scope", DEFAULT_SCOPE),
        targets=(),
        reviewers=tuple(parse_reviewer_key(k, DEFAULT_STRICTNESS) for k in reviewer_keys),
        context=(),
        output=output,
        output_file=output_file,
    )
