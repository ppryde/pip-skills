"""The query commands: diff-shaped (review-context, removed, ...) and name-shaped (callers, ...)."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from scripts.index import ensure_view
from scripts.query import Snippets, callers, guarding_tests
from scripts.render import Section, render
from scripts.resolve import Resolved, ViewIndex
from scripts.review import (
    Context,
    blindspot_sections,
    build,
    callers_section,
    contract_section,
    drift_section,
    footer,
    header,
    open_store,
    render_context,
    tests_section,
    touched_section,
    verdict_section,
    verdicts,
)
from scripts.views import worktree_view


def diff_command(args: argparse.Namespace, cwd: Path, stats: dict[str, object],
                 facts: dict[str, object]) -> tuple[str, int, str]:
    ctx = build(cwd, args.base, args.deadline)
    view_id = ctx.head.view_id
    n_verdicts = len(verdicts(ctx))
    facts.update(root=str(ctx.root), view_id=view_id, verdicts=n_verdicts, sections=[])
    stats.update(touched=len(ctx.diff.touched), files=ctx.head_cov.total,
                 verdicts=n_verdicts, repo_name=ctx.root.name)
    by_command: dict[str, Callable[[], list[Section]]] = {
        "removed": lambda: [contract_section(ctx)],
        "sig-drift": lambda: [verdict_section(ctx), drift_section(ctx)],
        "literals": lambda: blindspot_sections(ctx),
        "touched": lambda: [touched_section(ctx), callers_section(ctx), tests_section(ctx)],
    }
    if args.command == "review-context":
        rendered: list[Section] = []
        text = render_context(ctx, args.budget, stats, rendered)
        facts["sections"] = section_facts(rendered)
        return text, 0, view_id
    if args.command in by_command:
        sections = by_command[args.command]()
        facts["sections"] = section_facts(sections)
        return render(header(ctx), sections, footer(ctx), args.budget, stats), 0, view_id
    if args.command == "check":
        return check_text(ctx), (1 if n_verdicts else 0), view_id
    report = ctx.reports[0]
    summary = (f"head view {report.view_id}: {report.files} files, {report.parsed} parsed, "
               f"{report.reused} reused, {len(report.failed)} failed, "
               f"{len(report.skipped)} skipped")
    lines = [summary, *footer(ctx)]
    return "\n".join(lines), 0, view_id


def section_facts(sections: list[Section]) -> list[dict[str, object]]:
    return [{"title": s.title, "count": s.count} for s in sections]


def check_text(ctx: Context) -> str:
    lines = [f"[{v.rule}] {v.path}:{v.line}  {v.message}" for v in verdicts(ctx)]
    cov = footer(ctx)  # its first line is the summary; any more lines are coverage gaps
    return "\n".join((lines or ["check: clean"]) + (cov if len(cov) > 1 else []))


def name_command(args: argparse.Namespace, cwd: Path, stats: dict[str, object],
                 facts: dict[str, object]) -> tuple[str, int, str]:
    store = open_store(cwd)
    view = worktree_view(cwd)
    ensure_view(store, view, args.deadline)
    vi = ViewIndex(store, view)
    facts.update(root=str(view.root), view_id=view.view_id)
    if args.command == "coverage":
        cov = store.coverage(view.view_id)
        lines = [f"coverage: {cov.total - len(cov.not_indexed)}/{cov.total} files indexed",
                 *[f"  failed: {p} ({err})" for p, err in cov.failed],
                 *[f"  not indexed: {p}" for p in cov.not_indexed],
                 *[f"  not indexed ({why}): {p}" for p, why in sorted(view.skipped.items())]]
        return "\n".join(lines), 0, view.view_id
    facts.update(found=False, target=None, definition=None, hits=[])
    found = vi.lookup(args.name)
    if found.target is None:
        return miss_text(args.name, found), 0, view.view_id
    q = found.target
    facts.update(found=True, target=q, definition=vi.path_of(q))
    note = "" if found.confidence == "exact" else f" ({found.confidence} match for {args.name})"
    if args.command == "callers":
        found_callers = callers(vi, q, Snippets(view))
        places = [(h.path, h.line) for h in found_callers]
        rows = [f"{h.path}:{h.line} in {h.symbol} ({h.confidence})\n{h.snippet}"
                for h in found_callers]
        section = Section(f"Callers of {q}{note}", rows)
    else:
        found_tests = guarding_tests(vi, q, args.hops)
        places = [(t.path, t.line) for t in found_tests]
        rows = [f"{t.qualname} {t.path}:{t.line} ({t.hops} hop{'s' if t.hops > 1 else ''})"
                for t in found_tests]
        section = Section(f"Tests reaching {q}{note}", rows)
    if not section.rows:
        return f"{section.title}: none found", 0, view.view_id
    text = render([], [section], [], args.budget, stats)
    # hits are what the text shows: an agent cannot open what sits behind "+N more"
    cut, omitted = stats.get("cut"), stats.get("omitted")
    hidden = cut.get(section.title, 0) if isinstance(cut, dict) else 0
    shown = 0 if isinstance(omitted, list) and section.title in omitted else len(rows) - hidden
    facts["hits"] = [{"path": path, "line": line} for path, line in places[:shown]]
    return text, 0, view.view_id


def miss_text(name: str, found: Resolved) -> str:
    if found.confidence == "ambiguous":
        return f"{name} is ambiguous; did you mean: " + ", ".join(found.candidates)
    if found.candidates:
        return f"{name} not found; did you mean: " + ", ".join(found.candidates)
    return f"{name} not found in this worktree's view"
