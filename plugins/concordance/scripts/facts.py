"""The facts an extractor produces for one file. Plain data; no storage, no resolution.

A Ref's target is a raw name: an absolute dotted Python name ("pkg.mod.func"), "?.name" for a
call on a value whose type is unknown, "ts:<path-without-ext>.<member>" for TypeScript, or
"ts-bare:<specifier>|<member>" for a TS package import. resolve.py turns these into symbols.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # posonly | pos | vararg | kwonly | varkw
    has_default: bool


Signature = tuple[Param, ...]


@dataclass(frozen=True)
class CallShape:
    positional: int
    keywords: tuple[str, ...]
    star: bool
    dstar: bool


@dataclass(frozen=True)
class Symbol:
    qualname: str
    kind: str  # module | class | function | method | type | alias
    line_start: int
    line_end: int
    is_test: bool
    signature: Signature | None = None
    alias_of: str | None = None


@dataclass(frozen=True)
class Ref:
    src: str
    target: str
    kind: str  # call | name | inherit | decorator
    line: int
    args: CallShape | None = None


@dataclass(frozen=True)
class Literal:
    kind: str  # string | comment
    text: str
    line: int
    symbol: str


@dataclass(frozen=True)
class Guard:
    symbol: str
    kind: str  # if | raise | assert
    line: int
    text: str


@dataclass
class FileFacts:
    path: str
    blob_sha: str
    lang: str
    parsed_ok: bool
    error: str | None = None
    symbols: list[Symbol] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    literals: list[Literal] = field(default_factory=list)
    guards: list[Guard] = field(default_factory=list)


def signature_to_json(sig: Signature | None) -> str | None:
    if sig is None:
        return None
    return json.dumps([[p.name, p.kind, p.has_default] for p in sig])


def signature_from_json(raw: str | None) -> Signature | None:
    if raw is None:
        return None
    return tuple(Param(n, k, bool(d)) for n, k, d in json.loads(raw))


def shape_to_json(shape: CallShape | None) -> str | None:
    if shape is None:
        return None
    return json.dumps([shape.positional, list(shape.keywords), shape.star, shape.dstar])


def shape_from_json(raw: str | None) -> CallShape | None:
    if raw is None:
        return None
    pos, kws, star, dstar = json.loads(raw)
    return CallShape(int(pos), tuple(kws), bool(star), bool(dstar))


def file_facts_from_dict(d: dict[str, Any], blob_sha: str) -> FileFacts:
    """Build FileFacts from the TS extractor's JSON (same shape as the Python side)."""
    def sig(raw: Any) -> Signature | None:
        return None if raw is None else tuple(Param(n, k, bool(h)) for n, k, h in raw)

    def args(raw: Any) -> CallShape | None:
        if raw is None:
            return None
        return CallShape(raw["positional"], tuple(raw["keywords"]), raw["star"], raw["dstar"])

    return FileFacts(
        path=d["path"],
        blob_sha=blob_sha,
        lang=d["lang"],
        parsed_ok=bool(d["parsed_ok"]),
        error=d.get("error"),
        symbols=[
            Symbol(s["qualname"], s["kind"], s["line_start"], s["line_end"], bool(s["is_test"]),
                   sig(s.get("signature")), s.get("alias_of"))
            for s in d["symbols"]
        ],
        refs=[Ref(r["src"], r["target"], r["kind"], r["line"], args(r.get("args")))
              for r in d["refs"]],
        literals=[Literal(x["kind"], x["text"], x["line"], x["symbol"]) for x in d["literals"]],
        guards=[Guard(g["symbol"], g["kind"], g["line"], g["text"]) for g in d["guards"]],
    )
