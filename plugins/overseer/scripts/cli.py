"""Overseer ledger CLI — the interface the ledger skill drives.

Single-writer by convention: only the orchestrating session calls this.
Every mutation writes the card file first, then regenerates the index.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):  # direct script invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.index import rebuild_index  # noqa: E402
from scripts.models import Card, CardParseError, format_tokens, parse_tokens  # noqa: E402
from scripts.resume import format_report, handoff_data, handoff_report, resume_entries  # noqa: E402
from scripts.sprints import SPRINT_STATUSES, Sprint, load_sprint, rollup, save_sprint, sprint_path  # noqa: E402
from scripts.store import (  # noqa: E402
    archive_card,
    find_card_path,
    init_workflow,
    load_card,
    load_live_cards,
    mint_id,
    save_card,
    state_root,
)
from scripts.usage import append_usage, load_usage, summarise  # noqa: E402

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
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} updated")
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
    print(json.dumps(entries, indent=2) if args.json else format_report(entries))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    data = handoff_data(args.root)
    for path in data["quarantined"]:
        print(f"QUARANTINED: {path}", file=sys.stderr)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(handoff_report(args.root, data))
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
    p.set_defaults(func=cmd_set_field)

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

    p = sub.add_parser("handoff")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_handoff)

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
    except (CardParseError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
