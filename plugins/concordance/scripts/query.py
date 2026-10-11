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
class ContractGroup:
    """Everything removed from one symbol (or the symbol itself) and who still relies on it.
    `sites` are the sure-or-inferred references (the hard count); `ambiguous` call sites that
    could belong to the removed symbol or to a sibling of the same name are counted apart."""
    kind: str  # symbol | param | guard
    qualname: str
    removed: list[str]
    sites: list[Hit]
    ambiguous: int = 0


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


TOP_SITES = 3  # referencing sites listed per removed-contract group; the total stays exact


def _group_hit(snippets: Snippets, path: str, line: int, symbol: str, conf: str,
               note: str) -> Hit:
    return Hit(path, line, symbol, conf, note, snippets.around(path, line, ctx=0))


def _by_conf(hits: list[Hit]) -> list[Hit]:
    return sorted(hits, key=lambda h: (_CONF_RANK.get(h.confidence, 3), h.path, h.line))


def removed_contract(vi: ViewIndex, items: list[RemovedItem],
                     snippets: Snippets) -> list[ContractGroup]:
    """One group per removed symbol, per function that lost parameters, and per function that
    lost guards or decorators: what was removed, then the sites that still rely on it, once."""
    groups: list[ContractGroup] = []
    sym_items = [i for i in items if i.kind == "symbol"]
    for item in sym_items:
        sites: list[Hit] = []
        ambiguous = 0
        for path, ref in vi.refs_named(item.name):
            if vi.canonical(ref.target) == item.qualname:
                conf = "exact"
            elif ref.target.startswith("?.") and vi.resolve(ref.target).confidence == "ambiguous":
                ambiguous += 1  # may be a sibling method of the same name: not a hard claim
                continue
            elif ref.target.startswith("?.") and vi.resolve(ref.target).confidence == "unresolved":
                conf = "inferred"
            else:
                continue
            sites.append(_group_hit(snippets, path, ref.line, ref.src, conf,
                                    f"still references removed {item.qualname}"))
        groups.append(_group("symbol", item.qualname, [item.qualname], sites, ambiguous))
    owners: dict[tuple[str, str], list[RemovedItem]] = {}
    for item in items:
        if item.kind == "param":
            owners.setdefault(("param", item.qualname), []).append(item)
        elif item.kind in ("guard", "decorator"):
            owners.setdefault(("guard", item.qualname), []).append(item)
    for (kind, qualname), group_items in owners.items():
        if kind == "param":
            names = {i.name for i in group_items}
            sites = []
            for path, ref, conf in vi.callers_with_class(qualname):
                passed = sorted(names & set(ref.args.keywords)) if ref.args is not None else []
                if passed:
                    sites.append(_group_hit(snippets, path, ref.line, ref.src, conf,
                                            "still passes removed keyword "
                                            + ", ".join(f"`{n}`" for n in passed)))
            what = [f"param {i.name}" for i in group_items]
            groups.append(_group("param", qualname, what, sites, 0))
        else:
            tests = guarding_tests(vi, qualname)
            what = [f"guard {i.name} {i.text}".strip() if i.kind == "guard"
                    else f"decorator {i.name}" for i in group_items]
            expected = _expected_exceptions(group_items)
            test_names = {t.qualname for t in tests}
            expecting = {ref.src for name in expected for _p, ref in vi.refs_named(name)
                         if ref.src in test_names}
            sites = []
            for t in tests:
                note = "this test reaches it"
                if t.qualname in expecting:
                    note += " and references a removed exception"
                sites.append(_group_hit(snippets, t.path, t.line, t.qualname, "inferred", note))
            sites.sort(key=lambda h: (not h.note.endswith("exception"), h.path, h.line))
            groups.append(_group("guard", qualname, what, sites, 0))
    return groups


def _expected_exceptions(items: list[RemovedItem]) -> set[str]:
    out: set[str] = set()
    for i in items:
        if i.kind == "guard" and i.name == "raise":
            exc = re.match(r"[A-Za-z_][\w.]*", i.text)
            if exc:
                out.add(last(exc.group(0)))
    return out


def _group(kind: str, qualname: str, what: list[str], sites: list[Hit],
           ambiguous: int) -> ContractGroup:
    sites = sites if kind == "guard" else _by_conf(sites)
    seen: set[tuple[str, int]] = set()
    unique: list[Hit] = []
    for h in sites:
        if (h.path, h.line) not in seen:
            seen.add((h.path, h.line))
            unique.append(h)
    return ContractGroup(kind, qualname, what, unique, ambiguous)


def check_call(shape: CallShape, sig: Signature, bound: bool,
               binding_known: bool = True) -> tuple[str, str] | None:
    """Judge one call shape against a signature. `error` is a hard verdict: positional-count
    problems are only `error` when `binding_known` (a method may be called unbound)."""
    params = list(sig)
    if bound and params and params[0].name in ("self", "cls"):
        params = params[1:]
    if shape.star or shape.dstar:
        return ("undecided", "call passes *args or **kwargs")
    positional = [p for p in params if p.kind in ("posonly", "pos")]
    has_var = any(p.kind == "vararg" for p in params)
    has_varkw = any(p.kind == "varkw" for p in params)
    named = {p.name for p in params if p.kind in ("pos", "kwonly")}
    unknown = [k for k in shape.keywords if k not in named]
    if unknown and not has_varkw:
        return ("error", f"unknown keyword(s): {', '.join(unknown)}")
    covered = {p.name for p in positional[: shape.positional]}
    kwonly_missing = [p.name for p in params if p.kind == "kwonly" and not p.has_default
                      and p.name not in shape.keywords]
    if kwonly_missing:
        return ("error", f"missing required keyword-only: {', '.join(kwonly_missing)}")
    verdict = "error" if binding_known else "undecided"
    suffix = "" if binding_known else " (method binding unknown)"
    if shape.positional > len(positional) and not has_var:
        takes = len(positional)
        return (verdict, f"{shape.positional} positional args; signature takes {takes}{suffix}")
    if binding_known:
        twice = [k for k in shape.keywords if k in covered]
        if twice:
            return ("error", f"argument `{twice[0]}` given twice")
    missing = [p.name for p in positional
               if not p.has_default and p.name not in covered and p.name not in shape.keywords]
    if missing:
        return (verdict, f"missing required: {', '.join(missing)}{suffix}")
    return None


def sig_drift(vi: ViewIndex, changes: list[SignatureChange],
              snippets: Snippets) -> list[DriftHit]:
    out: list[DriftHit] = []
    for ch in changes:
        sym = vi.symbol(ch.qualname)
        is_method = sym is not None and sym.kind == "method"
        for path, ref, conf in vi.callers_with_class(ch.qualname):
            if ref.kind != "call":
                continue
            if conf == "ambiguous":
                verdict: tuple[str, str] | None = ("undecided", "call target is ambiguous")
            elif ref.args is None:
                verdict = ("undecided", "call shape is unknown")
            else:
                verdict = check_call(ref.args, ch.new, bound=is_method,
                                     binding_known=not is_method)
                if verdict is not None and verdict[0] == "error" and conf != "exact":
                    verdict = ("undecided", f"{verdict[1]} (target inferred by name)")
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
