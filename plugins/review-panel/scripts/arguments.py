"""Parse the /review-panel argument tokens into one request.

One token space, one precedence (RP-11):
  1. reserved words: reviewers, strategies (list and stop); full (scope),
     interactive, inline (output). Reserved words win over any name.
  2. a profile name from the config.
  3. a reviewer key: a built-in reviewer name or clone:<alias>.
  4. otherwise an error that lists every valid value.
A profile and reviewer keys never mix. Tokens are checked against a strict
name pattern before they get anywhere near a command line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.config import ConfigError

RESERVED = ("reviewers", "strategies", "full", "interactive", "inline")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


@dataclass(frozen=True)
class Request:
    list: str | None = None          # "reviewers" | "strategies"
    profile: str | None = None       # a named profile
    reviewers: tuple[str, ...] = ()  # ad-hoc reviewer keys
    scope: str | None = None         # "full" or None (keep the profile's)
    output: str | None = None        # "interactive" | "inline" or None


def _valid_values(profiles, reviewers) -> str:
    return (f"profiles {sorted(profiles) or '(none)'}, reviewers {sorted(reviewers)} "
            f"or clone:<alias>, words {list(RESERVED)}")


def parse_arguments(tokens: list[str], config: dict, reviewers: list[str],
                    strategies: list[str] | None = None) -> Request:
    profiles = (config or {}).get("profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}
    for t in tokens:
        if not isinstance(t, str) or not TOKEN_RE.match(t):
            raise ConfigError(f"invalid argument {t!r}: names use letters, digits, . _ : - only")
    scope = None
    outputs: list[str] = []
    rest: list[str] = []
    listing: list[str] = []
    for t in tokens:
        if t in ("reviewers", "strategies"):
            listing.append(t)
        elif t == "full":
            scope = "full"
        elif t in ("interactive", "inline"):
            outputs.append(t)
        else:
            rest.append(t)
    if len(set(outputs)) > 1:
        raise ConfigError("give one of interactive / inline, not both")
    output = outputs[0] if outputs else None
    if listing:
        if len(tokens) != 1:
            raise ConfigError(f"`{listing[0]}` takes no other arguments")
        return Request(list=listing[0])
    if not rest:
        return Request(scope=scope, output=output)  # the default profile
    in_profiles = [t for t in rest if t in profiles]
    if in_profiles:
        if len(rest) != 1:
            raise ConfigError("name one profile, or reviewers, not both: "
                              f"{_valid_values(profiles, reviewers)}")
        return Request(profile=rest[0], scope=scope, output=output)
    known = set(reviewers)
    bad = [t for t in rest if not (t in known or t.startswith("clone:"))]
    if bad:
        raise ConfigError(f"unknown argument {bad[0]!r}; valid: {_valid_values(profiles, reviewers)}")
    return Request(reviewers=tuple(rest), scope=scope, output=output)
