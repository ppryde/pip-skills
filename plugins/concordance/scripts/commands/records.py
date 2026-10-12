"""The usage-log commands: record-review, stats, replay and mode."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import modes, usage
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


def _replay_stats(args: argparse.Namespace) -> int:
    from scripts.replay import store as replay_store
    try:
        rep = replay_store.summary(days=args.days)
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    if args.json:
        common.say(json.dumps(rep, indent=2))
        return 0
    by_kind = rep["by_kind"]
    assert isinstance(by_kind, dict)
    head = (f"replay, last {rep['days']} days: {rep['sessions']} sessions, "
            f"{rep['rows']} calls, {rep['covered']} covered, {rep['uncovered']} uncovered "
            f"(session failures and pending replays: `chronicle concordance`)")
    lines = [head]
    for kind, k in sorted(by_kind.items()):
        a = k["answerable"]
        lines.append(f"{kind}: {k['calls']} calls, {k['covered']} covered, answerable "
                     f"{a['yes']}/{a['no']}/{a['unknown']}, drifted {k['drifted']}; "
                     f"all calls {k['actual_tokens']} tokens, with concordance "
                     f"{k['counterfactual_tokens']} (uncovered calls unchanged)")
        for ans in ("yes", "no", "unknown"):
            part = k["by_answerable"].get(ans)
            if part:
                lines.append(f"  answerable {ans}: {part['calls']} calls, actual "
                             f"{part['actual_tokens']} vs with concordance "
                             f"{part['counterfactual_tokens']}")
    common.say("\n".join(lines))
    return 0


def stats(args: argparse.Namespace, cwd: Path) -> int:
    if args.replay:
        return _replay_stats(args)
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


def replay(args: argparse.Namespace, cwd: Path) -> int:
    from scripts.replay import core, transcript
    from scripts.replay import store as replay_store
    try:
        files = transcript.session_files(
            args.session, main=Path(args.transcript) if args.transcript else None)
    except FileNotFoundError as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        return 2
    if not args.force and not transcript.is_finished(files):
        print("concordance: session not finished (idle < 15 min); use --force", file=sys.stderr)
        return 2
    session = transcript.load(args.session, files)
    home = next((Path(c.cwd) for c in session.calls if c.cwd and Path(c.cwd).is_dir()), cwd)
    rows = core.replay_session(session, modes.get_mode(args.session, common.repo_key_of(home)))
    try:
        replay_store.save(rows)
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    common.say(json.dumps(rows))
    return 0


def mode(args: argparse.Namespace, cwd: Path) -> int:
    repo = common.repo_key_of(cwd)
    if not repo and not args.session:
        print("concordance: mode needs a git repository or --session", file=sys.stderr)
        return 2
    modes.set_mode(args.mode, args.session, repo)
    scope = f"session {args.session}" if args.session else "repo default"
    common.say(f"mode: {args.mode} ({scope})")
    return 0
