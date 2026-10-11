"""Query-time name resolution within one view.

Facts store raw targets; resolving them against the view's own symbol table means two
worktrees with different code never contaminate each other's answers. Every answer carries a
confidence, and a miss is "ambiguous" or "unresolved" with candidates, never silence.
"""
from __future__ import annotations

import difflib
import json
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass

from scripts.facts import Ref, Symbol
from scripts.store import Store
from scripts.views import View

INIT = {"python": "__init__", "typescript": "constructor"}
_MAX_ALIAS_HOPS = 5
_CALLABLE = ("function", "method")


@dataclass(frozen=True)
class Resolved:
    target: str | None
    confidence: str  # exact | inferred | ambiguous | external | unresolved
    candidates: tuple[str, ...] = ()


def last(q: str) -> str:
    return q.rsplit(".", 1)[-1]


def parent(q: str) -> str:
    return q.rsplit(".", 1)[0]


def lang_of_qualname(q: str) -> str:
    return "typescript" if q.startswith("ts:") else "python"


def _load_ts_paths(view: View) -> tuple[str, list[tuple[str, str]]]:
    """(baseUrl, [(pattern, first target)]) from the view's root tsconfig.json, if any."""
    raw = view.read_extra("tsconfig.json")
    if raw is None:
        return ".", []
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        opts = json.loads(text).get("compilerOptions", {})
    except (json.JSONDecodeError, AttributeError):
        return ".", []
    base = str(opts.get("baseUrl", "."))
    pairs = [(str(pat), str(targets[0])) for pat, targets in (opts.get("paths") or {}).items()
             if isinstance(targets, list) and targets]
    return base, pairs


class ViewIndex:
    def __init__(self, store: Store, view: View) -> None:
        self.view = view
        self.symbols: dict[str, list[tuple[str, Symbol]]] = defaultdict(list)
        for path, sym in store.view_symbols(view.view_id):
            self.symbols[sym.qualname].append((path, sym))
        self.refs: list[tuple[str, Ref]] = store.view_refs(view.view_id)
        self._by_last: dict[str, list[str]] = defaultdict(list)
        self._modules_by_suffix: dict[str, set[str]] = defaultdict(set)
        for q, entries in self.symbols.items():
            kind = entries[0][1].kind
            if kind == "module":
                if not q.startswith("ts:"):
                    parts = q.split(".")
                    for i in range(len(parts)):
                        self._modules_by_suffix[".".join(parts[i:])].add(q)
            elif kind != "alias":
                self._by_last[last(q)].append(q)
        self._ts_base, self._ts_paths = _load_ts_paths(view)
        self._memo: dict[str, Resolved] = {}
        self._callers: dict[str, list[tuple[str, Ref, str]]] | None = None
        self._refs_by_last: dict[str, list[tuple[str, Ref]]] | None = None

    # -- symbol table ------------------------------------------------------------------------

    def symbol(self, q: str) -> Symbol | None:
        entries = self.symbols.get(q)
        return entries[0][1] if entries else None

    def path_of(self, q: str) -> str | None:
        entries = self.symbols.get(q)
        return entries[0][0] if entries else None

    def is_test(self, q: str) -> bool:
        sym = self.symbol(q)
        return bool(sym and sym.is_test)

    # -- resolution --------------------------------------------------------------------------

    def resolve(self, target: str) -> Resolved:
        hit = self._memo.get(target)
        if hit is None:
            hit = self._memo[target] = self._resolve(target, 0)
        return hit

    def _exact(self, q: str, depth: int) -> Resolved | None:
        sym = self.symbol(q)
        if sym is None:
            return None
        if sym.kind == "alias" and sym.alias_of:
            return self._resolve(sym.alias_of, depth + 1)
        return Resolved(q, "exact")

    def _resolve(self, target: str, depth: int) -> Resolved:
        if depth > _MAX_ALIAS_HOPS:
            return Resolved(None, "unresolved")
        if target.startswith("?."):
            name = target[2:]
            cands = sorted(q for q in self._by_last.get(name, [])
                           if (s := self.symbol(q)) is not None and s.kind in _CALLABLE)
            if len(cands) == 1:
                return Resolved(cands[0], "inferred")
            if cands:
                return Resolved(None, "ambiguous", tuple(cands[:5]))
            return Resolved(None, "unresolved")
        if target.startswith("ts-bare:"):
            spec, _, member = target[len("ts-bare:"):].partition("|")
            mapped = self._map_ts_bare(spec)
            if mapped is None:
                return Resolved(None, "external")
            return self._resolve(f"{mapped}.{member}" if member else mapped, depth + 1)
        direct = self._exact(target, depth)
        if direct is not None:
            return direct
        if target.startswith("ts:"):
            return self._resolve_ts_index(target, depth)
        full = self._python_full(target)
        if isinstance(full, Resolved):
            return full
        if full is None:
            return Resolved(None, "external")
        if full == target:
            return Resolved(None, "unresolved")
        return self._exact(full, depth) or Resolved(None, "unresolved")

    def _python_full(self, target: str) -> str | Resolved | None:
        """Map an absolute import name onto a module in this view by dotted-path suffix."""
        parts = target.split(".")
        for i in range(len(parts), 0, -1):
            mods = self._modules_by_suffix.get(".".join(parts[:i]))
            if not mods:
                continue
            rest = parts[i:]
            if len(mods) > 1:
                cands = sorted(".".join([m, *rest]) for m in mods)
                return Resolved(None, "ambiguous", tuple(cands[:5]))
            return ".".join([next(iter(mods)), *rest])
        return None

    def _resolve_ts_index(self, target: str, depth: int) -> Resolved:
        tail_start = target.rfind("/") + 1
        for i in [m.start() for m in re.finditer(r"\.", target[tail_start:])]:
            cut = tail_start + i
            alt = f"{target[:cut]}/index{target[cut:]}"
            hit = self._exact(alt, depth)
            if hit is not None:
                return hit
        return Resolved(None, "unresolved")

    def _map_ts_bare(self, spec: str) -> str | None:
        for pattern, dest in self._ts_paths:
            if "*" in pattern:
                prefix, _, suffix = pattern.partition("*")
                if spec.startswith(prefix) and spec.endswith(suffix):
                    middle = spec[len(prefix): len(spec) - len(suffix) if suffix else None]
                    mapped = dest.replace("*", middle)
                else:
                    continue
            elif spec == pattern:
                mapped = dest
            else:
                continue
            norm = posixpath.normpath(posixpath.join(self._ts_base, mapped))
            return "ts:" + re.sub(r"\.([cm]?[jt]sx?)$", "", norm)
        return None

    def canonical(self, target: str) -> str:
        """The target with its module mapped into this view, without requiring the member."""
        if target.startswith(("?.", "ts:", "ts-bare:")):
            return target
        full = self._python_full(target)
        return full if isinstance(full, str) else target

    def lookup(self, name: str) -> Resolved:
        if self.symbol(name) is not None:
            return self._exact(name, 0) or Resolved(name, "exact")
        r = self.resolve(name)
        if r.target:
            return r
        suffix = sorted(q for q in self.symbols
                        if q.endswith("." + name) and (s := self.symbol(q)) is not None
                        and s.kind != "alias")
        if len(suffix) == 1:
            return Resolved(suffix[0], "inferred")
        if suffix:
            return Resolved(None, "ambiguous", tuple(suffix[:8]))
        close = difflib.get_close_matches(last(name), list(self._by_last), n=5, cutoff=0.6)
        cands = tuple(q for n in close for q in sorted(self._by_last[n]))[:8]
        return Resolved(None, "unresolved", cands)

    # -- reverse edges -----------------------------------------------------------------------

    def callers(self, q: str) -> list[tuple[str, Ref, str]]:
        if self._callers is None:
            idx: dict[str, list[tuple[str, Ref, str]]] = defaultdict(list)
            for path, ref in self.refs:
                r = self.resolve(ref.target)
                if r.target:
                    idx[r.target].append((path, ref, r.confidence))
                elif r.confidence == "ambiguous":
                    for cand in r.candidates:
                        idx[cand].append((path, ref, "ambiguous"))
            self._callers = idx
        return list(self._callers.get(q, []))

    def callers_with_class(self, q: str) -> list[tuple[str, Ref, str]]:
        rows = self.callers(q)
        if last(q) == INIT[lang_of_qualname(q)]:
            rows += [row for row in self.callers(parent(q)) if row[1].kind == "call"]
        return rows

    def refs_named(self, name: str) -> list[tuple[str, Ref]]:
        if self._refs_by_last is None:
            idx: dict[str, list[tuple[str, Ref]]] = defaultdict(list)
            for path, ref in self.refs:
                idx[last(ref.target.split("|")[-1])].append((path, ref))
            self._refs_by_last = idx
        return list(self._refs_by_last.get(name, []))
