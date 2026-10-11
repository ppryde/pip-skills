"""Base vs head, per changed file: touched symbols, removed items, signature changes, and the
things an index cannot judge (changed literals, reordered statements, removed comments).
"""
from __future__ import annotations

import ast
import difflib
from collections import Counter
from dataclasses import dataclass, field

from scripts import classify
from scripts.facts import FileFacts, Signature, Symbol
from scripts.resolve import ViewIndex, last
from scripts.store import Store
from scripts.views import View, lang_of

_NOT_CODE = ("module", "alias", "type")


@dataclass(frozen=True)
class Touched:
    qualname: str
    path: str
    kind: str
    line: int
    behaviour_changed: bool
    is_new: bool


@dataclass(frozen=True)
class RemovedItem:
    kind: str  # symbol | param | guard | decorator
    qualname: str
    name: str
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class SignatureChange:
    qualname: str
    path: str
    line: int
    old: Signature
    new: Signature


@dataclass(frozen=True)
class LiteralChange:
    text: str
    change: str  # removed | added
    path: str
    line: int


@dataclass(frozen=True)
class Reorder:
    qualname: str
    path: str
    line: int


@dataclass(frozen=True)
class RemovedComment:
    path: str
    line: int
    text: str
    symbol: str


@dataclass
class DiffResult:
    changed_files: list[str]
    touched: list[Touched] = field(default_factory=list)
    removed: list[RemovedItem] = field(default_factory=list)
    signatures: list[SignatureChange] = field(default_factory=list)
    literals: list[LiteralChange] = field(default_factory=list)
    reorders: list[Reorder] = field(default_factory=list)
    removed_comments: list[RemovedComment] = field(default_factory=list)


def _decorator_starts(source: str) -> dict[int, int]:
    """Map a definition's own line to its first decorator line (symbols start at the def)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    return {n.lineno: min(d.lineno for d in n.decorator_list)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.decorator_list}


def _changed_lines(base_text: str, head_text: str,
                   def_lines: frozenset[int] = frozenset()) -> tuple[set[int], set[int]]:
    a, b = base_text.splitlines(), head_text.splitlines()
    base_lines: set[int] = set()
    head_lines: set[int] = set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        base_lines.update(range(i1 + 1, i2 + 1))
        if j2 > j1:
            head_lines.update(range(j1 + 1, j2 + 1))
        else:
            head_lines.add(max(j1, 1))  # a pure deletion touches the line before the gap
            if j1 + 1 in def_lines:  # ...and a definition right after it (removed decorator)
                head_lines.add(j1 + 1)
    return base_lines, head_lines


def _innermost(symbols: list[Symbol], lines: set[int],
               starts: dict[int, int] | None = None) -> list[Symbol]:
    starts = starts or {}

    def first(s: Symbol) -> int:
        return starts.get(s.line_start, s.line_start)

    claimed: set[int] = set()
    out: list[Symbol] = []
    for s in sorted(symbols, key=lambda s: s.line_end - first(s)):
        mine = {n for n in lines if first(s) <= n <= s.line_end} - claimed
        if mine:
            out.append(s)
            claimed |= mine
    return sorted(out, key=lambda s: s.line_start)


def _code_symbols(ff: FileFacts | None) -> dict[str, Symbol]:
    if ff is None or not ff.parsed_ok:
        return {}
    return {s.qualname: s for s in ff.symbols if s.kind not in _NOT_CODE}


def _norm(text: str) -> str:
    return "".join(text.split())


def analyse(store: Store, base: View, head: View, head_vi: ViewIndex) -> DiffResult:
    paths = sorted(p for p in set(base.files) | set(head.files)
                   if base.files.get(p) != head.files.get(p))
    base_src = {p: d.decode("utf-8", errors="replace")
                for p, d in base.read([p for p in paths if p in base.files]).items()}
    head_src = {p: d.decode("utf-8", errors="replace")
                for p, d in head.read([p for p in paths if p in head.files]).items()}
    result = DiffResult(changed_files=paths)
    for p in paths:
        bff = store.file_facts(p, base.files[p]) if p in base.files else None
        hff = store.file_facts(p, head.files[p]) if p in head.files else None
        b_text, h_text = base_src.get(p, ""), head_src.get(p, "")
        b_syms, h_syms = _code_symbols(bff), _code_symbols(hff)
        defs = frozenset(s.line_start for s in h_syms.values())
        _, h_lines = _changed_lines(b_text, h_text, defs)
        starts = _decorator_starts(h_text) if lang_of(p) == "python" else {}
        _touched(result, p, b_text, h_text, b_syms, h_syms, h_lines, starts)
        for q, s in b_syms.items():
            if q not in head_vi.symbols:
                result.removed.append(RemovedItem("symbol", q, last(q), p, s.line_start, ""))
        _signatures(result, p, b_syms, h_syms)
        if bff is not None and hff is not None and bff.parsed_ok and hff.parsed_ok:
            _guards_and_decorators(result, p, bff, hff, h_syms)
            _literals_and_comments(result, p, bff, hff, h_syms)
    return result


def _touched(result: DiffResult, p: str, b_text: str, h_text: str, b_syms: dict[str, Symbol],
             h_syms: dict[str, Symbol], h_lines: set[int], starts: dict[int, int]) -> None:
    is_python = lang_of(p) == "python"
    for s in _innermost(list(h_syms.values()), h_lines, starts):
        old = b_syms.get(s.qualname)
        if old is None:
            changed, new = True, True
        elif is_python:
            changed = classify.behaviour_changed(b_text, old.line_start, h_text, s.line_start)
            new = False
            if classify.reordered(b_text, old.line_start, h_text, s.line_start):
                result.reorders.append(Reorder(s.qualname, p, s.line_start))
        else:
            changed, new = True, False  # no TS classifier: assume behaviour changed
        result.touched.append(Touched(s.qualname, p, s.kind, s.line_start, changed, new))


def _signatures(result: DiffResult, p: str, b_syms: dict[str, Symbol],
                h_syms: dict[str, Symbol]) -> None:
    for q, old in b_syms.items():
        new = h_syms.get(q)
        if new is None or old.signature is None or new.signature is None:
            continue
        if old.signature != new.signature:
            result.signatures.append(SignatureChange(q, p, new.line_start,
                                                     old.signature, new.signature))
        kept = {x.name for x in new.signature}
        for param in old.signature:
            if param.name not in kept:
                result.removed.append(RemovedItem("param", q, param.name, p, old.line_start, ""))


def _guards_and_decorators(result: DiffResult, p: str, bff: FileFacts, hff: FileFacts,
                           h_syms: dict[str, Symbol]) -> None:
    head_guards = {(g.symbol, g.kind, _norm(g.text)) for g in hff.guards}
    for g in bff.guards:
        if g.symbol in h_syms and (g.symbol, g.kind, _norm(g.text)) not in head_guards:
            result.removed.append(RemovedItem("guard", g.symbol, g.kind, p, g.line, g.text))
    head_decs = {(r.src, r.target) for r in hff.refs if r.kind == "decorator"}
    for r in bff.refs:
        if r.kind == "decorator" and r.src in h_syms and (r.src, r.target) not in head_decs:
            result.removed.append(RemovedItem("decorator", r.src, r.target, p, r.line, r.target))


def _literals_and_comments(result: DiffResult, p: str, bff: FileFacts, hff: FileFacts,
                           h_syms: dict[str, Symbol]) -> None:
    def strings(ff: FileFacts) -> Counter[str]:
        return Counter(x.text for x in ff.literals if x.kind == "string")

    b_str, h_str = strings(bff), strings(hff)
    first_line: dict[tuple[bool, str], int] = {}
    for ff in (hff, bff):
        for x in ff.literals:
            if x.kind == "string":
                first_line.setdefault((ff is hff, x.text), x.line)
    for text in sorted((b_str - h_str).keys()):
        result.literals.append(LiteralChange(text, "removed", p, first_line[(False, text)]))
    for text in sorted((h_str - b_str).keys()):
        result.literals.append(LiteralChange(text, "added", p, first_line[(True, text)]))
    head_comments = {x.text for x in hff.literals if x.kind == "comment"}
    module = next((s.qualname for s in hff.symbols if s.kind == "module"), None)
    for x in bff.literals:
        if (x.kind == "comment" and x.text not in head_comments
                and (x.symbol in h_syms or x.symbol == module)):
            result.removed_comments.append(RemovedComment(p, x.line, x.text, x.symbol))
