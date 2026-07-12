"""Overseer ledger CLI — the interface the ledger skill drives.

Single-writer by convention: only the orchestrating session calls this.
Every mutation writes the card file first, then regenerates the index.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):  # direct script invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.calibration import BANDS, calibrate  # noqa: E402
from scripts.conflicts import find_conflicts  # noqa: E402
from scripts.index import rebuild_index  # noqa: E402
from scripts.models import (  # noqa: E402
    Card, CardParseError, PRIORITIES, format_tokens, parse_tokens,
)
from scripts.relations import would_cycle_depends, would_cycle_parent  # noqa: E402
from scripts.resume import format_report, handoff_data, handoff_report, resume_entries  # noqa: E402
from scripts.sprints import (  # noqa: E402
    SPRINT_STATUSES,
    Sprint,
    load_sprint,
    retro_rollup,
    rollup,
    save_sprint,
    sprint_path,
)
from scripts.store import (  # noqa: E402
    archive_card,
    find_card_path,
    init_workflow,
    load_archived_cards,
    load_card,
    load_live_cards,
    mint_id,
    save_card,
    state_root,
)
from scripts.usage import append_usage, load_usage, summarise  # noqa: E402
from scripts.knowledge import (  # noqa: E402
    Fact,
    FactParseError,
    ensure_kb,
    find_fact_path,
    knowledge_root,
    load_fact,
    load_facts,
    mint_fact_id,
    rebuild_knowledge_index,
    retire_fact_file,
    save_fact,
)

CARD_BODY_TEMPLATE = """## Goal
{goal}

## Plan
_(pending)_

## Decisions

## Review log

## Progress log

## Verification
"""

SPRINT_BODY_TEMPLATE = """## Goal
{goal}

## Cards
| Card | Complexity | Est | Actual | Status |
|---|---|---|---|---|

## Conflicts

## Retro
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _report_quarantined(quarantined: list[Path]) -> None:
    for path in quarantined:
        print(f"QUARANTINED: {path}", file=sys.stderr)


def _vigil_cli() -> Path | None:
    """Best-effort locate the sibling vigil plugin's CLI (soft dependency)."""
    here = Path(__file__).resolve()  # plugins/overseer/scripts/cli.py
    candidate = here.parent.parent.parent / "vigil" / "scripts" / "cli.py"
    return candidate if candidate.exists() else None


def _vigil_context(repo_root: Path) -> str | None:
    """Run `vigil context`; return its line, or None if vigil is absent/errors."""
    cli = _vigil_cli()
    if cli is None:
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(cli), "--root", str(repo_root), "context"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip()
    return line or None


def _context_footer(repo_root: Path) -> str:
    """`\\nctx NN%` when vigil is installed and reports a real percentage; else ''."""
    line = _vigil_context(repo_root)
    if line and line.startswith("ctx ") and line != "ctx unknown":
        return "\n" + line
    return ""


def _sync(repo_root: Path, card: Card) -> None:
    """Write ordering per spec: card first, then the index view."""
    root = state_root(repo_root)
    save_card(root, card)
    quarantined = rebuild_index(repo_root, repo_root.resolve().name, _now())
    _report_quarantined(quarantined)


def _load(repo_root: Path, card_id: str) -> Card:
    return load_card(find_card_path(state_root(repo_root), card_id))


def cmd_init(args: argparse.Namespace) -> int:
    init_workflow(args.root)
    rebuild_index(args.root, args.root.resolve().name, _now())
    print(f"initialised {state_root(args.root)}")
    return 0


def cmd_new_card(args: argparse.Namespace) -> int:
    root = state_root(args.root)
    card_id = args.jira or args.linear or mint_id(root)
    try:
        find_card_path(root, card_id)
    except FileNotFoundError:
        pass
    else:
        print(f"error: card {card_id} already exists", file=sys.stderr)
        return 1
    card = Card(
        id=card_id,
        title=args.title,
        status="planned",
        jira=args.jira,
        linear=args.linear,
        complexity=args.complexity,
        sprint=args.sprint,
        budget_estimate=parse_tokens(args.estimate),
        created=_today(),
        updated=_now(),
        body=CARD_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    _sync(args.root, card)
    print(card.id)
    return 0


def cmd_set_stage(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.set_stage(args.stage, _now())
    _sync(args.root, card)
    print(f"{card.id} → {args.stage}")
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.block(args.reason, _now())
    _sync(args.root, card)
    print(f"{card.id} blocked: {args.reason}")
    return 0


def cmd_unblock(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.unblock(_now())
    _sync(args.root, card)
    print(f"{card.id} → {card.status}")
    return 0


def _close(args: argparse.Namespace, verb: str) -> int:
    card = _load(args.root, args.card_id)
    card.complete(_now()) if verb == "done" else card.abandon(_now())
    root = state_root(args.root)
    archive_card(root, card)
    rebuild_index(args.root, args.root.resolve().name, _now())
    print(f"{card.id} {card.status}, archived")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    return _close(args, "done")


def cmd_abandon(args: argparse.Namespace) -> int:
    return _close(args, "abandon")


def cmd_set_field(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    if args.branch:
        card.branch = args.branch
    if args.worktree:
        card.worktree = args.worktree
    if args.pr:
        card.pr = args.pr
    if args.touches is not None:
        card.touches = [t.strip() for t in args.touches.split(",") if t.strip()]
    if args.order is not None:
        card.order = args.order
    if args.priority is not None:
        if args.priority == "":
            card.priority = None
        else:
            if args.priority not in PRIORITIES:
                print(f"error: unknown priority: {args.priority!r}", file=sys.stderr)
                return 1
            card.priority = args.priority
    if args.parent is not None:
        if args.parent == "":
            card.parent = None
        else:
            cards, _ = load_live_cards(state_root(args.root))
            if args.parent not in {c.id for c in cards}:
                print(f"error: no live card {args.parent}", file=sys.stderr)
                return 1
            if would_cycle_parent(cards, args.card_id, args.parent):
                print(f"error: parent {args.parent} would create a cycle",
                      file=sys.stderr)
                return 1
            card.parent = args.parent
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} updated")
    return 0


def cmd_depends(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    cards, _ = load_live_cards(state_root(args.root))
    ids = {c.id for c in cards}
    if args.on:
        if args.on == args.card_id:
            print("error: a card cannot depend on itself", file=sys.stderr)
            return 1
        if args.on not in ids:
            print(f"error: no live card {args.on}", file=sys.stderr)
            return 1
        if would_cycle_depends(cards, args.card_id, args.on):
            print(f"error: depending on {args.on} would create a cycle",
                  file=sys.stderr)
            return 1
        if args.on not in card.depends_on:
            card.depends_on.append(args.on)
    if args.off and args.off in card.depends_on:
        card.depends_on.remove(args.off)
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} depends_on: {', '.join(card.depends_on) or '(none)'}")
    return 0


def cmd_park(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.park(_now())
    _sync(args.root, card)
    print(f"{card.id} parked")
    return 0


def cmd_unpark(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.unpark(_now())
    _sync(args.root, card)
    print(f"{card.id} → {card.status}")
    return 0


def cmd_log_progress(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    tokens = parse_tokens(args.tokens) or 0
    card.log_progress(args.note, tokens, _now())
    _sync(args.root, card)
    if card.tripwire_breached:
        actual = format_tokens(card.budget_actual)
        estimate = format_tokens(card.budget_estimate)
        print(
            f"TRIPWIRE: {card.id} at {actual} vs estimate {estimate} — "
            "stop this card and escalate to the user",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_log_review(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.log_review(args.stage, args.reviewers, args.verdict, _now())
    _sync(args.root, card)
    print(f"{card.id} {args.stage} round {card.review_rounds(args.stage)} logged")
    return 0


def cmd_new_sprint(args: argparse.Namespace) -> int:
    sprint = Sprint(
        id=args.sprint_id,
        status="planned",
        budget_estimate=parse_tokens(args.estimate),
        started=_today(),
        body=SPRINT_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    save_sprint(state_root(args.root), sprint)
    print(sprint.id)
    return 0


def cmd_rollup_sprint(args: argparse.Namespace) -> int:
    root = state_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    cards, quarantined = load_live_cards(root)
    _report_quarantined(quarantined)
    save_sprint(root, rollup(sprint, cards))
    print(f"{args.sprint_id} rolled up")
    return 0


def cmd_set_sprint_status(args: argparse.Namespace) -> int:
    root = state_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    sprint.status = args.status
    if args.status == "closed":
        live, quarantined = load_live_cards(root)
        _report_quarantined(quarantined)
        sprint = retro_rollup(sprint, live + load_archived_cards(root))
    save_sprint(root, sprint)
    print(f"{sprint.id} → {args.status}")
    return 0


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    quarantined = rebuild_index(args.root, args.root.resolve().name, _now())
    _report_quarantined(quarantined)
    print("index rebuilt")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    _, quarantined = load_live_cards(state_root(args.root))
    _report_quarantined(quarantined)
    entries = resume_entries(args.root)
    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        print(format_report(entries) + _context_footer(args.root))
    return 0


def cmd_conflicts(args: argparse.Namespace) -> int:
    cards, quarantined = load_live_cards(state_root(args.root))
    _report_quarantined(quarantined)
    if args.sprint:
        cards = [c for c in cards if c.sprint == args.sprint]
    conflicts = find_conflicts(cards)
    if args.json:
        print(json.dumps([[a, b, paths] for a, b, paths in conflicts], indent=2))
        return 0
    if not conflicts:
        print("No conflicts.")
        return 0
    for a, b, paths in conflicts:
        print(f"{a} ~ {b}: {', '.join(paths)}")
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    data = handoff_data(args.root)
    for path in data["quarantined"]:
        print(f"QUARANTINED: {path}", file=sys.stderr)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(handoff_report(args.root, data) + _context_footer(args.root))
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    from scripts.board import board_data
    data = board_data(args.root)
    _report_quarantined([Path(p) for p in data["quarantined"]])
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        card_count = len(data["cards"])
        sprint_count = len(data["sprints"])
        print(f"{card_count} cards, {sprint_count} sprints")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        card = _load(args.root, args.id)
    except FileNotFoundError:
        root = state_root(args.root)
        matches = sorted((root / "archive" / "cards").glob(f"{args.id}-*.md"))
        if not matches:
            raise FileNotFoundError(f"no card with id {args.id}")
        card = load_card(matches[0])
    data = {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "stage": card.stage,
        "order": card.order,
        "complexity": card.complexity,
        "priority": card.priority,
        "jira": card.jira,
        "linear": card.linear,
        "sprint": card.sprint,
        "parent": card.parent,
        "branch": card.branch,
        "worktree": card.worktree,
        "pr": card.pr,
        "touches": card.touches,
        "depends_on": card.depends_on,
        "budget": {
            "estimate": card.budget_estimate,
            "actual": card.budget_actual,
        },
        "created": card.created,
        "updated": card.updated,
        "blocked_on": card.blocked_on,
        "checklist": card.checklist,
        "sections": card.sections,
        "body": card.body,
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print(f"{card.id} — {card.title} [{card.status}/{card.stage or '-'}]")
    for header in card.sections:
        print(f"  {header or '(preamble)'}")
    return 0


def cmd_log_usage(args: argparse.Namespace) -> int:
    entry = {
        "ts": _now(),
        "card": args.card_id,
        "role": args.role,
        "stage": args.stage,
        "tier": args.tier,
        "tokens": parse_tokens(args.tokens) or 0,
        "round": args.round,
    }
    append_usage(state_root(args.root), entry)
    print(f"usage logged: {args.card_id} {args.role} {args.tokens}")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    entries, skipped = load_usage(state_root(args.root))
    if skipped:
        print(f"warning: {skipped} corrupt usage line(s) skipped", file=sys.stderr)
    summary = summarise(entries, args.card)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    if not summary["total"]:
        print("No usage recorded.")
        return 0
    lines = [f"# Usage — total: {format_tokens(summary['total'])}", "", "## By role"]
    lines += [f"- {r}: {format_tokens(t)}" for r, t in sorted(summary["by_role"].items())]
    lines += ["", "## By card"]
    lines += [f"- {c}: {format_tokens(t)}" for c, t in sorted(summary["by_card"].items())]
    print("\n".join(lines))
    return 0


def cmd_calibration(args: argparse.Namespace) -> int:
    cards = load_archived_cards(state_root(args.root))
    report = calibrate(cards)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    total = sum(report["bands"][b]["count"] for b in BANDS)
    if not total:
        if report["skipped"]:
            print(
                f"{report['skipped']} completed card(s) skipped "
                "(no estimate or no actual); no calibratable samples."
            )
        else:
            print("No completed cards to calibrate from.")
        return 0
    lines = ["# Calibration (actual ÷ estimate)", ""]
    for b in BANDS:
        band = report["bands"][b]
        if not band["count"]:
            lines.append(f"- {b}: no samples")
            continue
        mult = f", suggest ×{band['multiplier']}" if band["multiplier"] else ""
        lines.append(
            f"- {b}: n={band['count']}, median {band['median']}, "
            f"mean {band['mean']}{mult}"
        )
    if report["skipped"]:
        lines.append(f"\n_{report['skipped']} completed card(s) skipped "
                     "(no estimate or no actual)._")
    print("\n".join(lines))
    return 0


def cmd_add_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    ensure_kb(kb)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    fact = Fact(
        id=mint_fact_id(kb),
        statement=args.statement,
        tags=tags,
        source=args.source,
        created=_today(),
        verified=_today(),
        status="active",
        body=args.body or "",
    )
    save_fact(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(fact.id)
    return 0


def cmd_verify_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    fact = load_fact(find_fact_path(kb, args.fact_id))
    fact.verified = _today()
    fact.status = "active"
    save_fact(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(f"{fact.id} verified {fact.verified}")
    return 0


def cmd_retire_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    fact = load_fact(find_fact_path(kb, args.fact_id))
    fact.status = "retired"
    fact.superseded_by = args.superseded_by
    retire_fact_file(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(f"{fact.id} retired")
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    facts, quarantined = load_facts(kb)
    _report_quarantined(quarantined)
    today = _today()
    rows = []
    for f in facts:
        effective = f.effective_status(today)
        if args.tag and args.tag not in f.tags:
            continue
        if args.stale and effective != "stale":
            continue
        rows.append({
            "id": f.id,
            "statement": f.statement,
            "tags": f.tags,
            "verified": f.verified,
            "status": effective,
        })
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No stale facts." if args.stale else "No facts.")
        return 0
    for r in rows:
        mark = " [STALE]" if r["status"] == "stale" else ""
        tags = ", ".join(r["tags"]) or "no tags"
        print(f"{r['id']} ({tags}){mark}: {r['statement']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overseer", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p = sub.add_parser("new-card")
    p.add_argument("--title", required=True)
    ref = p.add_mutually_exclusive_group()
    ref.add_argument("--jira")
    ref.add_argument("--linear")
    p.add_argument("--complexity", choices=["S", "M", "L"])
    p.add_argument("--sprint")
    p.add_argument("--estimate")
    p.add_argument("--goal")
    p.set_defaults(func=cmd_new_card)

    p = sub.add_parser("set-stage")
    p.add_argument("card_id")
    p.add_argument("stage")
    p.set_defaults(func=cmd_set_stage)

    p = sub.add_parser("block")
    p.add_argument("card_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_block)

    p = sub.add_parser("unblock")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unblock)

    for name, func in (("done", cmd_done), ("abandon", cmd_abandon)):
        p = sub.add_parser(name)
        p.add_argument("card_id")
        p.set_defaults(func=func)

    p = sub.add_parser("set-field")
    p.add_argument("card_id")
    p.add_argument("--branch")
    p.add_argument("--worktree")
    p.add_argument("--pr")
    p.add_argument("--touches")
    p.add_argument("--parent")
    p.add_argument("--order", type=int)
    p.add_argument("--priority")
    p.set_defaults(func=cmd_set_field)

    p = sub.add_parser("depends")
    p.add_argument("card_id")
    p.add_argument("--on")
    p.add_argument("--off")
    p.set_defaults(func=cmd_depends)

    p = sub.add_parser("park")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_park)

    p = sub.add_parser("unpark")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unpark)

    p = sub.add_parser("log-progress")
    p.add_argument("card_id")
    p.add_argument("--note", required=True)
    p.add_argument("--tokens", required=True)
    p.set_defaults(func=cmd_log_progress)

    p = sub.add_parser("log-review")
    p.add_argument("card_id")
    p.add_argument("--stage", required=True)
    p.add_argument("--reviewers", type=int, required=True)
    p.add_argument("--verdict", required=True)
    p.set_defaults(func=cmd_log_review)

    p = sub.add_parser("new-sprint")
    p.add_argument("sprint_id")
    p.add_argument("--estimate")
    p.add_argument("--goal")
    p.set_defaults(func=cmd_new_sprint)

    p = sub.add_parser("rollup-sprint")
    p.add_argument("sprint_id")
    p.set_defaults(func=cmd_rollup_sprint)

    p = sub.add_parser("set-sprint-status")
    p.add_argument("sprint_id")
    p.add_argument("status", choices=sorted(SPRINT_STATUSES))
    p.set_defaults(func=cmd_set_sprint_status)

    sub.add_parser("rebuild-index").set_defaults(func=cmd_rebuild_index)

    p = sub.add_parser("resume")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("conflicts")
    p.add_argument("--sprint")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_conflicts)

    p = sub.add_parser("handoff")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("board")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_board)

    p = sub.add_parser("show")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("log-usage")
    p.add_argument("card_id")
    p.add_argument(
        "--role",
        required=True,
        choices=["planner", "worker", "reviewer", "fixer", "orchestrator"],
    )
    p.add_argument("--tokens", required=True)
    p.add_argument("--stage")
    p.add_argument("--tier")
    p.add_argument("--round", type=int)
    p.set_defaults(func=cmd_log_usage)

    p = sub.add_parser("usage")
    p.add_argument("--card")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_usage)

    p = sub.add_parser("calibration")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_calibration)

    p = sub.add_parser("add-fact")
    p.add_argument("--statement", required=True)
    p.add_argument("--tags")
    p.add_argument("--source")
    p.add_argument("--body")
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("verify-fact")
    p.add_argument("fact_id")
    p.set_defaults(func=cmd_verify_fact)

    p = sub.add_parser("retire-fact")
    p.add_argument("fact_id")
    p.add_argument("--superseded-by", dest="superseded_by")
    p.set_defaults(func=cmd_retire_fact)

    p = sub.add_parser("facts")
    p.add_argument("--tag")
    p.add_argument("--stale", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_facts)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse --help (0) or usage error (2)
        return 0 if not exc.code else 1
    try:
        result: int = args.func(args)
        return result
    except (CardParseError, FactParseError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
