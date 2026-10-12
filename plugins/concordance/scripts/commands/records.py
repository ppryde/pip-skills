"""The usage-log commands: record-review and stats."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import usage
from scripts.commands import common


def parse_steps(text: str) -> dict[str, int]:
    steps: dict[str, int] = {}
    for part in filter(None, text.split(",")):
        step, sep, count = part.partition(":")
        if not sep or not step.strip().isdigit() or not count.strip().isdigit():
            raise ValueError(f"--steps expects step:count pairs like 1:2,3:1, got {part!r}")
        steps[step.strip()] = int(count)
    return steps


def record_review(args: argparse.Namespace, cwd: Path) -> int:
    if not 0 <= args.via_index <= args.findings:
        print("concordance: --via-index must be between 0 and --findings", file=sys.stderr)
        return 2
    try:
        steps = parse_steps(args.steps)
    except ValueError as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        return 2
    if sum(steps.values()) > args.findings:
        print("concordance: --steps counts exceed --findings", file=sys.stderr)
        return 2
    try:
        usage.record("record-review", common.repo_key_of(cwd), None, 0, 0, 0,
                     {"findings": args.findings, "via_index": args.via_index, "steps": steps},
                     session=common.session_id())
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    common.say(f"recorded review: {args.findings} findings ({args.via_index} via concordance)")
    return 0


def stats(args: argparse.Namespace, cwd: Path) -> int:
    repo = common.repo_key_of(cwd) if args.repo == "this" else None
    if args.repo == "this" and not repo:
        print("concordance: --repo this needs a git repository", file=sys.stderr)
        return 2
    try:
        rep = usage.report(days=args.days, repo=repo)
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    common.say(json.dumps(rep, indent=2) if args.json else usage.format_report(rep))
    return 0
