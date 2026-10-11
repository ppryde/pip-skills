"""Deterministic review queries. Each returns hits with a line and a code snippet, so the agent
judges meaning without opening files; two of them (signature drift, test gaps) return verdicts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.diff import LiteralChange, RemovedItem, SignatureChange, Touched
from scripts.facts import CallShape, Signature
from scripts.resolve import ViewIndex, last
from scripts.store import Store
from scripts.views import View

_CONF_RANK = {"exact": 0, "inferred": 1, "ambiguous": 2}
_TESTABLE = ("function", "method", "class")


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    symbol: str
    confidence: str
    note: str
    snippet: str = ""


class Snippets:
    def __init__(self, view: View) -> None:
        self.view = view
        self._cache: dict[str, list[str]] = {}

    def around(self, path: str, line: int, ctx: int = 0) -> str:
        lines = self._cache.get(path)
        if lines is None:
            lines = self._cache[path] = self.view.text(path).splitlines()
        lo, hi = max(1, line - ctx), min(len(lines), line + ctx)
        return "\n".join(f"{n:>6}| {lines[n - 1]}" for n in range(lo, hi + 1))


@dataclass(frozen=True)
class TestHit:
    __test__ = False  # not a pytest class, despite the name

    qualname: str
    path: str
    line: int
    hops: int


@dataclass(frozen=True)
class ContractHit:
    item: RemovedItem
    hit: Hit


@dataclass(frozen=True)
class DriftHit:
    change: SignatureChange
    hit: Hit
    verdict: str  # error | undecided
    reason: str


@dataclass(frozen=True)
class LiteralHit:
    change: LiteralChange
    elsewhere: list[tuple[str, int]]


def callers(vi: ViewIndex, q: str, snippets: Snippets) -> list[Hit]:
    seen: set[tuple[str, int]] = set()
    hits: list[Hit] = []
    for path, ref, conf in vi.callers_with_class(q):
        if (path, ref.line) in seen:
            continue
        seen.add((path, ref.line))
        hits.append(Hit(path, ref.line, ref.src, conf, ref.kind,
                        snippets.around(path, ref.line)))
    return sorted(hits, key=lambda h: (vi.is_test(h.symbol), _CONF_RANK.get(h.confidence, 3),
                                       h.path, h.line))


def guarding_tests(vi: ViewIndex, q: str, hops: int = 2) -> list[TestHit]:
    seen = {q}
    frontier = {q}
    found: dict[str, TestHit] = {}
    for hop in range(1, hops + 1):
        nxt: set[str] = set()
        for target in sorted(frontier):
            for path, ref, _conf in vi.callers_with_class(target):
                src = ref.src
                if src in seen:
                    continue
                seen.add(src)
                sym = vi.symbol(src)
                if sym is None:
                    continue
                if sym.is_test:
                    found.setdefault(src, TestHit(src, path, ref.line, hop))
                elif sym.kind != "module":
                    nxt.add(src)
        frontier = nxt
    return sorted(found.values(), key=lambda t: (t.hops, t.path, t.line))


def _contract(item: RemovedItem, snippets: Snippets, path: str, line: int, symbol: str,
              conf: str, note: str) -> ContractHit:
    return ContractHit(item, Hit(path, line, symbol, conf, note,
                                 snippets.around(path, line, ctx=2)))


def removed_contract(vi: ViewIndex, items: list[RemovedItem],
                     snippets: Snippets) -> list[ContractHit]:
    out: list[ContractHit] = []
    for item in items:
        if item.kind == "symbol":
            for path, ref in vi.refs_named(item.name):
                if vi.canonical(ref.target) == item.qualname:
                    conf = "exact"
                elif ref.target.startswith("?.") and vi.resolve(ref.target).target is None:
                    conf = "inferred"
                else:
                    continue
                out.append(_contract(item, snippets, path, ref.line, ref.src, conf,
                                     f"still references removed {item.qualname}"))
        elif item.kind == "param":
            for path, ref, conf in vi.callers_with_class(item.qualname):
                if ref.args is not None and item.name in ref.args.keywords:
                    out.append(_contract(item, snippets, path, ref.line, ref.src, conf,
                                         f"still passes removed keyword `{item.name}`"))
        else:  # guard or decorator: the tests that exercise the symbol may rely on it
            if item.kind == "guard":
                what = f"guard removed from {item.qualname}: {item.name} {item.text}"
            else:
                what = f"decorator {item.name} removed from {item.qualname}"
            for t in guarding_tests(vi, item.qualname):
                out.append(_contract(item, snippets, t.path, t.line, t.qualname, "inferred",
                                     f"{what}; this test reaches it"))
            if item.kind == "guard" and item.name == "raise":
                exc = re.match(r"[A-Za-z_][\w.]*", item.text)
                if exc:
                    for path, ref in vi.refs_named(last(exc.group(0))):
                        if vi.is_test(ref.src):
                            out.append(_contract(
                                item, snippets, path, ref.line, ref.src, "inferred",
                                f"test expects {exc.group(0)}, raised by the removed guard"))
    return out


def check_call(shape: CallShape, sig: Signature, bound: bool) -> tuple[str, str] | None:
    params = list(sig)
    if bound and params and params[0].name in ("self", "cls"):
        params = params[1:]
    if shape.star or shape.dstar:
        return ("undecided", "call passes *args or **kwargs")
    positional = [p for p in params if p.kind in ("posonly", "pos")]
    has_var = any(p.kind == "vararg" for p in params)
    has_varkw = any(p.kind == "varkw" for p in params)
    if shape.positional > len(positional) and not has_var:
        return ("error", f"{shape.positional} positional args; signature takes {len(positional)}")
    named = {p.name for p in params if p.kind in ("pos", "kwonly")}
    unknown = [k for k in shape.keywords if k not in named]
    if unknown and not has_varkw:
        return ("error", f"unknown keyword(s): {', '.join(unknown)}")
    covered = {p.name for p in positional[: shape.positional]} | set(shape.keywords)
    missing = [p.name for p in params if p.kind in ("posonly", "pos", "kwonly")
               and not p.has_default and p.name not in covered]
    if missing:
        return ("error", f"missing required: {', '.join(missing)}")
    return None


def sig_drift(vi: ViewIndex, changes: list[SignatureChange],
              snippets: Snippets) -> list[DriftHit]:
    out: list[DriftHit] = []
    for ch in changes:
        sym = vi.symbol(ch.qualname)
        bound = sym is not None and sym.kind == "method"
        for path, ref, conf in vi.callers_with_class(ch.qualname):
            if ref.kind != "call":
                continue
            if conf == "ambiguous" or ref.args is None:
                verdict: tuple[str, str] | None = ("undecided", "call target is ambiguous")
            else:
                verdict = check_call(ref.args, ch.new, bound)
            if verdict is not None:
                out.append(DriftHit(ch, Hit(path, ref.line, ref.src, conf, verdict[1],
                                            snippets.around(path, ref.line)), *verdict))
    return out


def untested_changes(vi: ViewIndex, touched: list[Touched]) -> list[Touched]:
    return [t for t in touched
            if t.behaviour_changed and t.kind in _TESTABLE and not vi.is_test(t.qualname)
            and not guarding_tests(vi, t.qualname)]


def literal_hits(store: Store, view_id: str, changes: list[LiteralChange]) -> list[LiteralHit]:
    occurrences = store.literal_occurrences(view_id, sorted({c.text for c in changes}))
    out: list[LiteralHit] = []
    for c in changes:
        elsewhere = [(p, line) for text, p, line in occurrences if text == c.text and p != c.path]
        out.append(LiteralHit(c, elsewhere))
    return out
