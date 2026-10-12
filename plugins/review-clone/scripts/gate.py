#!/usr/bin/env python3
"""review-clone's side of pip-agents (WF-270 PR F): briefs for `pip-agents:gatekeeper` and `pip-agents:reviewer-rules`,
and the checks of what they return. Run by absolute path, JSON on stdout, files hold the data:

    gate.py brief-collect --alias A --handles H1,H2 --repo O/N --months N [--paths P] [--extensions E]
                          [--incremental | --since ISO] --work-dir DIR
    gate.py check-collect --brief FILE --message FILE
    gate.py batches       --alias A --target DIFF --work-dir DIR
    gate.py review-ingest --brief FILE --message FILE --out FILE

brief-collect writes the gatekeeper brief for one `collect.py` run (the command line is built here from validated
values; the gatekeeper refuses any shell metacharacter). check-collect validates the gatekeeper's reply with the
vendored pip-agents validator and prints the snapshot path and counts, never the corpus. batches says whether a persona
fits the 30-rule cap (review stays inline) or writes rulebooks and briefs for `reviewer-rules`; review-ingest validates
one such reply and appends its candidate findings to --out. Exit 0 ok; 1 refused, failed or rejected; 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # this file may run under `python3 -I`

import persona_io  # noqa: E402
from clone_rulebook import BATCH_CAP, clone_exceptions, clone_rules, plan, render, validator  # noqa: E402

COLLECT = Path(__file__).resolve().parent / "collect.py"
TIMEOUT_MS = 600_000
COUNT_NAMES = "pr_count,comment_count,error_count"
WINDOW_CAP_MONTHS = 6
_REPO = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_HANDLE = re.compile(r"[A-Za-z0-9-]+")
_FILTER = re.compile(r"[A-Za-z0-9._/@+-]+")
_SINCE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9:.]+(?:Z|[+-][0-9:]+)?)?")
_BAD_PATH_CHARS = set("'\"\\`$|&;<>\n\r\0 ")
CLONE_GATES = (
    "target is a unified diff of the change under review: judge the added and changed lines; the rest of each file "
    "is context.\n"
    "These rules are a cloned reviewer's. Report a rule only when the code it names exists in this repository "
    "(confirm a named symbol with Grep; absent: the rule is n_a). Every finding's `citation` is that rule's "
    "Citation URL; a rule with none is unchecked. The Allowed exceptions span lists what this reviewer let go: "
    "do not report it.\n"
)


class GateError(Exception):
    """A value is malformed or hostile, or a file is missing (exit 1)."""


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout)
    sys.stdout.write("\n")


def _private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def _clean_path(value: str | Path, what: str) -> str:
    s = str(Path(value).resolve())
    if set(s) & _BAD_PATH_CHARS:
        raise GateError(f"{what} contains a character the gatekeeper refuses: {s!r}")
    return s


def _filters(value: str, what: str) -> str:
    items = [x for x in (value or "").split(",") if x]
    for item in items:
        if not _FILTER.fullmatch(item):
            raise GateError(f"{what} entry {item!r} has characters outside [A-Za-z0-9._/@+-]")
    return ",".join(items)


def _brief_text(fields: dict[str, str]) -> str:
    text = "".join(f"{k}: {v}\n" for k, v in fields.items())
    vr = validator()
    errors = vr.check_brief(vr.parse_brief(text))
    if errors:
        raise GateError("brief is not valid: " + "; ".join(errors))
    return text


def collect_command(args) -> str:
    persona_io.check_alias(args.alias, persona_io.PERSONA_ROOT)  # strict slug for a new alias, traversal-only for an old one
    if not _REPO.fullmatch(args.repo):
        raise GateError(f"repo {args.repo!r} is not owner/name")
    handles = [h for h in args.handles.split(",") if h]
    if not handles or not all(_HANDLE.fullmatch(h) for h in handles):
        raise GateError("handles must be comma-separated GitHub logins ([A-Za-z0-9-]+)")
    if not 1 <= args.months <= WINDOW_CAP_MONTHS:
        raise GateError(f"--months must be 1..{WINDOW_CAP_MONTHS}")
    if args.since and not _SINCE.fullmatch(args.since):
        raise GateError(f"--since {args.since!r} is not an ISO date")
    parts = [
        "python3", _clean_path(COLLECT, "collect.py path"),
        "--alias", f"'{args.alias}'", "--handles", f"'{','.join(handles)}'", "--repo", f"'{args.repo}'",
        "--months", str(args.months),
        f"--paths='{_filters(args.paths, 'paths')}'", f"--extensions='{_filters(args.extensions, 'extensions')}'",
    ]
    if args.incremental:
        parts.append("--incremental")
    elif args.since:
        parts += ["--since", f"'{args.since}'"]
    return " ".join(parts)


def cmd_brief_collect(args) -> dict:
    run = collect_command(args)
    out = persona_io.persona_dir(args.alias) / "snapshot.json"
    text = _brief_text({"brief": "pip-agents/1", "kind": "run", "ref": "collect", "run": run,
                        "timeout_ms": str(TIMEOUT_MS), "out": _clean_path(out, "snapshot path"), "counts": COUNT_NAMES})
    brief = Path(args.work_dir) / "brief-collect.txt"
    _private_write(brief, text)
    return {"status": "ok", "persona": "pip-agents:gatekeeper", "brief": str(brief.resolve()), "prompt": text,
            "out": str(out)}


def _read(path: str, what: str) -> str:
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > 2_000_000:
            raise OSError("not a regular file within 2 MB")
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GateError(f"cannot read {what} {path}: {exc}") from exc


def _parse(args, persona: str):
    vr = validator()
    try:
        brief = vr.parse_brief(_read(args.brief, "brief"))
    except ValueError as exc:
        raise GateError(f"brief: {exc}") from exc
    env, errors = vr.parse_result(_read(args.message, "message"), brief, persona)
    return brief, env, errors


def cmd_check_collect(args) -> tuple[dict, int]:
    _, env, errors = _parse(args, "gatekeeper")
    if errors or env is None:
        return {"status": "rejected", "errors": errors}, 1
    if env["status"] == "error":
        return {"status": "refused", "error": env["error"]}, 1
    p = env["payload"]
    if p["exit_code"] != 0 or p["timed_out"]:
        return {"status": "failed", "exit_code": p["exit_code"], "timed_out": p["timed_out"],
                "stderr_tail": p.get("stderr_tail", "")}, 1
    return {"status": "ok", "snapshot": p["out"], "counts": p["counts"],
            "injection_attempts": env["injection_attempts"]}, 0


def _persona_body(alias: str) -> str:
    found = persona_io.locate_persona(alias)
    if found is None:
        raise GateError(f"persona {alias} not found")
    return persona_io._split_body(found[0])


def cmd_batches(args) -> dict:
    persona_io.safe_alias(args.alias)
    body = _persona_body(args.alias)
    rules = clone_rules(args.alias, body)
    if not rules:
        raise GateError(f"persona {args.alias} has no rules")
    if len(rules) <= BATCH_CAP:
        return {"status": "ok", "inline": True, "rules": len(rules)}
    work = Path(args.work_dir)
    exceptions = clone_exceptions(body)
    batches = plan(args.alias, rules)
    target = _clean_path(args.target, "target")
    context = work / f"context-{args.alias}.md"
    _private_write(context, CLONE_GATES)
    seats = []
    for k, batch in enumerate(batches, 1):
        book = work / f"rules-{args.alias}-{k}.md"
        text = render(args.alias, batch, exceptions)
        _private_write(book, text)
        ids = ",".join(r.id for r in batch)
        brief_text = _brief_text({
            "brief": "pip-agents/1", "kind": "review", "ref": args.alias, "target": target,
            "rules": f"{_clean_path(book, 'rulebook')} L1-{len(text.splitlines())} ({ids})",
            "context": _clean_path(context, "context"),
        })
        bfile = work / f"brief-{args.alias}-{k}.txt"
        _private_write(bfile, brief_text)
        seats.append({"ref": args.alias, "persona": "pip-agents:reviewer-rules", "batch": f"{k}/{len(batches)}",
                      "brief": str(bfile.resolve()), "prompt": brief_text})
    return {"status": "ok", "inline": False, "rules": len(rules), "seats": seats}


def cmd_review_ingest(args) -> tuple[dict, int]:
    _, env, errors = _parse(args, "reviewer-rules")
    if errors or env is None:
        return {"status": "rejected", "errors": errors}, 1
    if env["status"] == "error":
        return {"status": "ok", "findings": 0, "seat_error": env["error"],
                "injection_attempts": env["injection_attempts"]}, 0
    p = env["payload"]
    out = Path(args.out)
    cands: list = []
    if out.exists():
        try:
            cands = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GateError(f"cannot read {args.out}: {exc}") from exc
        if not isinstance(cands, list):
            raise GateError(f"{args.out} must hold a JSON list")
    new = [{**f, "tier": "medium" if f in p["medium"] else None} for f in p["findings"] + p["medium"]]
    cands += new
    _private_write(out, json.dumps(cands, indent=2) + "\n")
    return {"status": "ok", "findings": len(new), "rules_checked": p.get("rules_checked"), "n_a": p.get("n_a", []),
            "unchecked": env["unchecked"], "injection_attempts": env["injection_attempts"]}, 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gate.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief-collect")
    b.add_argument("--alias", required=True)
    b.add_argument("--handles", required=True)
    b.add_argument("--repo", required=True)
    b.add_argument("--months", type=int, default=WINDOW_CAP_MONTHS)
    b.add_argument("--paths", default="")
    b.add_argument("--extensions", default="")
    b.add_argument("--incremental", action="store_true")
    b.add_argument("--since")
    b.add_argument("--work-dir", required=True)
    c = sub.add_parser("check-collect")
    c.add_argument("--brief", required=True)
    c.add_argument("--message", required=True)
    bt = sub.add_parser("batches")
    bt.add_argument("--alias", required=True)
    bt.add_argument("--target", required=True)
    bt.add_argument("--work-dir", required=True)
    r = sub.add_parser("review-ingest")
    r.add_argument("--brief", required=True)
    r.add_argument("--message", required=True)
    r.add_argument("--out", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "brief-collect":
            result, code = cmd_brief_collect(args), 0
        elif args.cmd == "check-collect":
            result, code = cmd_check_collect(args)
        elif args.cmd == "batches":
            result, code = cmd_batches(args), 0
        else:
            result, code = cmd_review_ingest(args)
    except (GateError, ValueError, OSError) as exc:
        _emit({"status": "error", "error": str(exc)})
        return 1
    _emit(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
