"""review-context: one call that builds both views, analyses the diff, runs every query and
renders the result within a budget. Also the source of `check`'s verdicts (BR-002, BR-005).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from scripts import extract_ts, gitio
from scripts.diff import DiffResult, Touched, analyse
from scripts.index import BuildReport, ensure_view
from scripts.paths import store_path
from scripts.query import (
    ContractGroup,
    DriftHit,
    LiteralHit,
    Snippets,
    callers,
    guarding_tests,
    literal_hits,
    removed_contract,
    sig_drift,
    untested_changes,
)
from scripts.render import Section, render
from scripts.resolve import ViewIndex
from scripts.store import Coverage, Store
from scripts.views import View, base_view, lang_of, worktree_view

TOP_CALLERS = 3
TOP_CONTRACT_SITES = 3


@dataclass(frozen=True)
class Verdict:
    rule: str
    path: str
    line: int
    message: str


@dataclass
class Context:
    root: Path
    store: Store
    head: View
    base: View
    base_label: str
    reports: list[BuildReport]
    vi: ViewIndex
    diff: DiffResult
    snippets: Snippets
    contract: list[ContractGroup]
    drift: list[DriftHit]
    gaps: list[Touched]
    literals: list[LiteralHit]
    head_cov: Coverage
    base_cov: Coverage


def open_store(cwd: Path) -> Store:
    return Store(store_path(gitio.common_dir(cwd)))


def build(cwd: Path, base_ref: str | None, deadline_s: float) -> Context:
    root = gitio.worktree_root(cwd)
    store = open_store(root)
    if base_ref is None:
        branch = gitio.default_branch(root)
        try:
            base_sha = gitio.merge_base(root, branch)
        except gitio.GitError as exc:
            raise gitio.GitError(f"no merge-base with {branch}; pass --base <ref> ({exc})") from exc
        label = f"merge-base with {branch}"
    else:
        base_sha = gitio.rev_parse(root, base_ref)
        label = base_ref
    start = time.monotonic()
    head = worktree_view(root)
    base = base_view(root, base_sha)
    reports = [ensure_view(store, head, deadline_s)]
    reports.append(ensure_view(store, base, max(5.0, deadline_s - (time.monotonic() - start))))
    vi = ViewIndex(store, head)
    snippets = Snippets(head)
    d = analyse(store, base, head, vi)
    return Context(
        root=root, store=store, head=head, base=base, base_label=label, reports=reports, vi=vi,
        diff=d, snippets=snippets,
        contract=removed_contract(vi, d.removed, snippets),
        drift=sig_drift(vi, d.signatures, snippets),
        gaps=untested_changes(vi, d.touched),
        literals=literal_hits(store, head.view_id, d.literals),
        head_cov=store.coverage(head.view_id),
        base_cov=store.coverage(base.view_id),
    )


def verdicts(ctx: Context) -> list[Verdict]:
    out = [Verdict("BR-002", x.hit.path, x.hit.line,
                   f"{x.hit.symbol} → {x.change.qualname}: {x.reason}")
           for x in ctx.drift if x.verdict == "error"]
    out += [Verdict("BR-005", t.path, t.line,
                    f"{t.qualname} changed behaviour and no test reaches it within 2 hops")
            for t in ctx.gaps]
    return out


def header(ctx: Context) -> list[str]:
    d = ctx.diff
    changed = sum(t.behaviour_changed and not t.is_new for t in d.touched)
    new = sum(t.is_new for t in d.touched)
    refactor = len(d.touched) - changed - new
    sha = ctx.base.ref[:7] if ctx.base.ref else "?"
    line1 = (f"concordance — base {ctx.base_label} ({sha}); "
             "head: this worktree incl. uncommitted edits; paths relative to the worktree root")
    line2 = (f"changed files: {len(d.changed_files)} · touched symbols: {len(d.touched)} "
             f"({changed} behaviour-changed, {refactor} refactor-only, {new} new)")
    return [line1, line2]


def _not_indexed_reason(path: str) -> str:
    if lang_of(path) == "typescript":
        reason = extract_ts.unavailable_reason()
        if reason:
            return reason
    return "deadline"


def footer(ctx: Context) -> list[str]:
    cov = ctx.head_cov
    indexed = cov.total - len(cov.not_indexed)
    lines = [f"coverage: {indexed}/{cov.total} files indexed in the head view"]
    if cov.failed:
        shown = ", ".join(f"{p} ({err})" for p, err in cov.failed[:5])
        more = f" +{len(cov.failed) - 5} more" if len(cov.failed) > 5 else ""
        lines.append(f"  failed to parse: {shown}{more}")
    if cov.not_indexed:
        reasons = sorted({_not_indexed_reason(p) for p in cov.not_indexed})
        shown = ", ".join(cov.not_indexed[:5])
        more = f" +{len(cov.not_indexed) - 5} more" if len(cov.not_indexed) > 5 else ""
        lines.append(f"  not indexed ({'; '.join(reasons)}): {shown}{more}"
                     " — for these files do steps 1-4 by grep")
    if ctx.base_cov.not_indexed:
        lines.append(f"  base view: {len(ctx.base_cov.not_indexed)} files not indexed; "
                     "removed-item detection is incomplete for them")
    return lines


def verdict_section(ctx: Context) -> Section:
    rows = [f"[{v.rule}] {v.path}:{v.line}  {v.message}" for v in verdicts(ctx)]
    return Section("Verdicts", rows, seed=True)


def contract_section(ctx: Context) -> Section:
    rows = []
    for g in ctx.contract:
        shown = ", ".join(g.removed[:5]) + (f" +{len(g.removed) - 5} more"
                                            if len(g.removed) > 5 else "")
        if g.kind == "symbol":
            head = f"[removed symbol] {g.qualname}"
        elif g.kind == "param":
            head = f"[removed params] {g.qualname}: {shown}"
        else:
            head = f"[removed guards] {g.qualname}: {shown}"
        if not g.sites and not g.ambiguous:
            continue
        lines = [f"{head} — {len(g.sites)} site(s)" if g.sites else head]
        for h in g.sites[:TOP_CONTRACT_SITES]:
            lines.append(f"  {h.path}:{h.line} in {h.symbol} ({h.confidence}): {h.note}\n"
                         f"{h.snippet}")
        if len(g.sites) > TOP_CONTRACT_SITES:
            lines.append(f"  +{len(g.sites) - TOP_CONTRACT_SITES} more site(s) (exact)")
        if g.ambiguous:
            lines.append(f"  low confidence, not counted: {g.ambiguous} call(s) by the same "
                         "name that may belong to a sibling symbol")
        rows.append("\n".join(lines))
    return Section("Removed contract", rows)


def drift_section(ctx: Context) -> Section:
    rows = [f"{x.hit.path}:{x.hit.line} in {x.hit.symbol} → {x.change.qualname}: {x.reason}\n"
            f"{x.hit.snippet}" for x in ctx.drift if x.verdict == "undecided"]
    return Section("Signature drift, undecided", rows)


def touched_section(ctx: Context) -> Section:
    rows = []
    for t in ctx.diff.touched:
        status = "new" if t.is_new else ("behaviour-changed" if t.behaviour_changed
                                         else "refactor-only")
        n_callers = len(ctx.vi.callers_with_class(t.qualname))
        n_tests = len(guarding_tests(ctx.vi, t.qualname))
        rows.append(f"{t.qualname}  {t.path}:{t.line}  {status}  callers {n_callers}  "
                    f"tests {n_tests}")
    return Section("Touched symbols", rows)


def callers_section(ctx: Context) -> Section:
    rows = []
    for t in ctx.diff.touched:
        if not t.behaviour_changed or t.is_new:
            continue
        hits = callers(ctx.vi, t.qualname, ctx.snippets)
        if not hits:
            continue
        lines = [f"{t.qualname}: {len(hits)} caller(s)"]
        lines += [f"  {h.path}:{h.line} in {h.symbol} ({h.confidence})\n{h.snippet}"
                  for h in hits[:TOP_CALLERS]]
        rows.append("\n".join(lines))
    return Section("Callers of behaviour-changed symbols", rows)


def tests_section(ctx: Context) -> Section:
    rows = []
    for t in ctx.diff.touched:
        if not t.behaviour_changed:
            continue
        tests = guarding_tests(ctx.vi, t.qualname)
        if tests:
            listed = ", ".join(f"{x.qualname} ({x.path}:{x.line}, {x.hops} hop"
                               f"{'s' if x.hops > 1 else ''})" for x in tests[:5])
            more = f" +{len(tests) - 5} more" if len(tests) > 5 else ""
            rows.append(f"{t.qualname}: {listed}{more}")
    return Section("Guarding tests", rows)


def blindspot_sections(ctx: Context) -> list[Section]:
    lit_rows = []
    for h in ctx.literals:
        text = h.change.text if len(h.change.text) <= 80 else h.change.text[:77] + "..."
        where = ", ".join(f"{p}:{n}" for p, n in h.elsewhere[:5]) or "nowhere else"
        lit_rows.append(f"[{h.change.change}] {text!r} {h.change.path}:{h.change.line} "
                        f"— also at {where}")
    reorder_rows = [f"{r.qualname} {r.path}:{r.line}: statements reordered"
                    for r in ctx.diff.reorders]
    comment_rows = [f"{c.path}:{c.line} in {c.symbol}: # {c.text}"
                    for c in ctx.diff.removed_comments]
    return [Section("Changed literals", lit_rows), Section("Reordered statements", reorder_rows),
            Section("Removed comments", comment_rows)]


def render_context(ctx: Context, budget: int, stats: dict[str, object] | None = None) -> str:
    sections = [verdict_section(ctx), contract_section(ctx), drift_section(ctx),
                touched_section(ctx), callers_section(ctx), tests_section(ctx),
                *blindspot_sections(ctx)]
    return render(header(ctx), sections, footer(ctx), budget, stats)
