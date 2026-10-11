"""concordance CLI. Run as `python <plugin>/scripts/cli.py <command>` from inside a worktree."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put the plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import extract_ts, gitio, paths, usage
from scripts.index import LockTimeout, ensure_view
from scripts.query import Snippets, callers, guarding_tests
from scripts.render import Section, est_tokens, render
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

DEFAULT_BUDGET = 1500
REVIEW_BUDGET = 4000  # provisional: tune from the usage log (render stats + diff size)
DEFAULT_DEADLINE = 60.0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="concordance", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, diff: bool = True, name_arg: bool = False) -> None:
        sp = sub.add_parser(name, help=help_text)
        if name_arg:
            sp.add_argument("name")
        if diff:
            sp.add_argument("--base", default=None,
                            help="base ref (default: merge-base with the default branch)")
        sp.add_argument("--budget", type=int,
                        default=REVIEW_BUDGET if name == "review-context" else DEFAULT_BUDGET)
        sp.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE)

    add("index", "build or refresh this worktree's view (and the base view)")
    add("review-context", "everything a reviewer needs for this diff, within a budget")
    add("removed", "references to what the diff removed")
    add("sig-drift", "call sites that no longer match a changed signature")
    add("literals", "changed literals, reordered statements, removed comments")
    add("touched", "touched symbols, callers of changed behaviour, guarding tests")
    add("check", "verdicts only (BR-002, BR-005); exit 1 when any")
    add("callers", "who calls NAME", diff=False, name_arg=True)
    add("tests", "tests that reach NAME within --hops", diff=False, name_arg=True)
    sub.choices["tests"].add_argument("--hops", type=int, default=2)
    add("coverage", "files indexed, failed and skipped in this worktree's view", diff=False)
    sub.add_parser("setup-ts", help="install the pinned TypeScript parser (npm ci)")
    rr = sub.add_parser("record-review", help="record a finished review's findings (usage log)")
    rr.add_argument("--findings", type=int, required=True)
    rr.add_argument("--via-index", type=int, required=True)
    rr.add_argument("--steps", default="", help="findings per procedure step, e.g. 1:2,3:1")
    st = sub.add_parser("stats", help="usage and effectiveness report from the usage log")
    st.add_argument("--days", type=int, default=30)
    st.add_argument("--repo", choices=("this", "all"), default="all")
    st.add_argument("--json", action="store_true")
    return p


def _diff_command(args: argparse.Namespace, cwd: Path,
                  stats: dict[str, object]) -> tuple[str, int, str]:
    ctx = build(cwd, args.base, args.deadline)
    view_id = ctx.head.view_id
    stats.update(touched=len(ctx.diff.touched), files=ctx.head_cov.total,
                 verdicts=len(verdicts(ctx)), repo_name=ctx.root.name)
    by_command: dict[str, Callable[[], list[Section]]] = {
        "removed": lambda: [contract_section(ctx)],
        "sig-drift": lambda: [verdict_section(ctx), drift_section(ctx)],
        "literals": lambda: blindspot_sections(ctx),
        "touched": lambda: [touched_section(ctx), callers_section(ctx), tests_section(ctx)],
    }
    if args.command == "review-context":
        return render_context(ctx, args.budget, stats), 0, view_id
    if args.command in by_command:
        sections = by_command[args.command]()
        return render(header(ctx), sections, footer(ctx), args.budget, stats), 0, view_id
    if args.command == "check":
        return _check(ctx), (1 if verdicts(ctx) else 0), view_id
    report = ctx.reports[0]
    summary = (f"head view {report.view_id}: {report.files} files, {report.parsed} parsed, "
               f"{report.reused} reused, {len(report.failed)} failed, "
               f"{len(report.skipped)} skipped")
    lines = [summary, *footer(ctx)]
    return "\n".join(lines), 0, view_id


def _check(ctx: Context) -> str:
    lines = [f"[{v.rule}] {v.path}:{v.line}  {v.message}" for v in verdicts(ctx)]
    cov = footer(ctx)  # its first line is the summary; any more lines are coverage gaps
    return "\n".join((lines or ["check: clean"]) + (cov if len(cov) > 1 else []))


def _name_command(args: argparse.Namespace, cwd: Path,
                  stats: dict[str, object]) -> tuple[str, int, str]:
    store = open_store(cwd)
    view = worktree_view(cwd)
    ensure_view(store, view, args.deadline)
    vi = ViewIndex(store, view)
    if args.command == "coverage":
        cov = store.coverage(view.view_id)
        lines = [f"coverage: {cov.total - len(cov.not_indexed)}/{cov.total} files indexed",
                 *[f"  failed: {p} ({err})" for p, err in cov.failed],
                 *[f"  not indexed: {p}" for p in cov.not_indexed]]
        return "\n".join(lines), 0, view.view_id
    found = vi.lookup(args.name)
    if found.target is None:
        return _miss(args.name, found), 0, view.view_id
    q = found.target
    note = "" if found.confidence == "exact" else f" ({found.confidence} match for {args.name})"
    if args.command == "callers":
        hits = callers(vi, q, Snippets(view))
        rows = [f"{h.path}:{h.line} in {h.symbol} ({h.confidence})\n{h.snippet}" for h in hits]
        section = Section(f"Callers of {q}{note}", rows)
    else:
        tests = guarding_tests(vi, q, args.hops)
        rows = [f"{t.qualname} {t.path}:{t.line} ({t.hops} hop{'s' if t.hops > 1 else ''})"
                for t in tests]
        section = Section(f"Tests reaching {q}{note}", rows)
    if not section.rows:
        return f"{section.title}: none found", 0, view.view_id
    return render([], [section], [], args.budget, stats), 0, view.view_id


def _miss(name: str, found: Resolved) -> str:
    if found.confidence == "ambiguous":
        return f"{name} is ambiguous; did you mean: " + ", ".join(found.candidates)
    if found.candidates:
        return f"{name} not found; did you mean: " + ", ".join(found.candidates)
    return f"{name} not found in this worktree's view"


def _repo(cwd: Path) -> str:
    try:
        return paths.repo_key(gitio.common_dir(cwd))
    except gitio.GitError:
        return ""


def _parse_steps(text: str) -> dict[str, int]:
    steps: dict[str, int] = {}
    for part in filter(None, text.split(",")):
        step, sep, count = part.partition(":")
        if not sep or not step.strip().isdigit() or not count.strip().isdigit():
            raise ValueError(f"--steps expects step:count pairs like 1:2,3:1, got {part!r}")
        steps[step.strip()] = int(count)
    return steps


def _say(text: str) -> None:
    """Print to stdout; a closed pipe (`| head`) is a quiet end, not a traceback."""
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())  # silence exit-time flush


def _record_review(args: argparse.Namespace, cwd: Path) -> int:
    if not 0 <= args.via_index <= args.findings:
        print("concordance: --via-index must be between 0 and --findings", file=sys.stderr)
        return 2
    try:
        steps = _parse_steps(args.steps)
    except ValueError as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        return 2
    if sum(steps.values()) > args.findings:
        print("concordance: --steps counts exceed --findings", file=sys.stderr)
        return 2
    try:
        usage.record("record-review", _repo(cwd), None, 0, 0, 0,
                     {"findings": args.findings, "via_index": args.via_index, "steps": steps},
                     session=os.environ.get("CLAUDE_SESSION_ID", ""))
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    _say(f"recorded review: {args.findings} findings ({args.via_index} via concordance)")
    return 0


def _stats(args: argparse.Namespace, cwd: Path) -> int:
    repo = _repo(cwd) if args.repo == "this" else None
    if args.repo == "this" and not repo:
        print("concordance: --repo this needs a git repository", file=sys.stderr)
        return 2
    try:
        rep = usage.report(days=args.days, repo=repo)
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    _say(json.dumps(rep, indent=2) if args.json else usage.format_report(rep))
    return 0


def _log(command: str, cwd: Path, view_id: str | None, started: float, text: str, code: int,
         payload: dict[str, object]) -> None:
    try:
        usage.record(command, _repo(cwd), view_id, int((time.monotonic() - started) * 1000),
                     est_tokens(text), code, payload,
                     session=os.environ.get("CLAUDE_SESSION_ID", ""))
    except Exception:  # noqa: BLE001, S110 - the usage log must never fail a query
        pass


def _utf8_streams() -> None:
    """Never let an odd terminal encoding turn output into a traceback."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = _parser().parse_args(argv)
    if args.command == "setup-ts":
        return extract_ts.setup()
    cwd = Path.cwd()
    if args.command == "record-review":
        return _record_review(args, cwd)
    if args.command == "stats":
        return _stats(args, cwd)
    started = time.monotonic()
    stats: dict[str, object] = {}
    try:
        if args.command in ("callers", "tests", "coverage"):
            text, code, view_id = _name_command(args, cwd, stats)
        else:
            text, code, view_id = _diff_command(args, cwd, stats)
    except (gitio.GitError, LockTimeout) as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        _log(args.command, cwd, None, started, "", 2, {"error": type(exc).__name__})
        return 2
    except Exception as exc:  # noqa: BLE001 - internal error: exit 2, never a bare traceback
        print(f"concordance: internal error: {exc!r}", file=sys.stderr)
        _log(args.command, cwd, None, started, "", 2, {"error": type(exc).__name__})
        return 2
    _say(text)
    _log(args.command, cwd, view_id, started, text, code, stats)
    return code


if __name__ == "__main__":
    sys.exit(main())
