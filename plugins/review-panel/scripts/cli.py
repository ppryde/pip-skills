#!/usr/bin/env python3
"""review-panel command line: the deterministic steps of a review.

Run as a script, no PYTHONPATH needed:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" <command> ...

JSON in, JSON out (stdout), exit 0 on success. Findings travel in files the
orchestrator wrote with the Write tool; finding text is never an argument.

  resolve    config + profile/reviewers -> the resolved review
               --config PATH  [--profile NAME | --reviewer KEY ...]
               [--scope changed|full] [--output report|inline|interactive]
               | --list reviewers|strategies
             stdout {"status":"ok","review":{strategy,scope,targets,reviewers:
             [{key,source,name,strictness}],context,output,output_file}}
             {"status":"config-missing"} exit 3 when the config file is absent;
             {"status":"error","error":...} exit 1 on a bad config/request.

  parse      reviewer payloads -> findings with fingerprints
               --findings FILE
             FILE: a JSON list of reviewer payloads (or one payload).
             stdout {"status":"ok","findings":[...],"clean_files":[...],"notes":[...]}
             Notes carry `REJECTED <id>: <reason>` for malformed findings.

  match      two independent passes -> agreed / disagreements (dual-tiebreaker)
               --a FILE --b FILE [--window 3]
             stdout {"status":"ok","agreed":[...],"only_a":[...],"only_b":[...],
             "notes":[...]}; fingerprints are final across all three lists.

  reconcile  verdicts -> strictness -> decisions
               --findings FILE [--verdicts FILE] [--require-verdicts]
               [--strictness REVIEWER=LEVEL ...] [--decisions FILE]
               [--reviewers-dir DIR] [--out FILE]
             --findings: a list of reviewer payloads, or the `parse` output
             ({"findings":[flat findings with "reviewer"]}), or the `match`
             output (agreed + only_a + only_b are reconciled together).
             --verdicts: {"<fingerprint>": {"verdict": "confirmed|refuted|weakened",
             "reason": "..."}}; a missing file is fine, an unknown fingerprint
             is noted.
             stdout {"status":"ok","findings":[...],"dropped":[...],"notes":[...],
             "counts":{"error":n,"warning":n,"info":n,"refuted":n,"unverified":n}}

  report     reconcile output -> markdown (stdout), also written to --out
               --reconciled FILE --strategy NAME --scope NAME [--out FILE]
             Refuted findings are listed in a trailing section, never lost.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# Imports below resolve `scripts.*` against this plugin whatever the cwd or
# PYTHONPATH is. Drop this file's own directory so a stray sibling module can
# never shadow a stdlib name.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(_ROOT))

from scripts.config import (  # noqa: E402
    VALID_OUTPUT, VALID_SCOPE, VALID_STRICTNESS,
    ConfigError, load_config, resolve_adhoc, resolve_profile,
)
from scripts.contract import (  # noqa: E402
    VALID_SEVERITY, ContractError, _as_list, assign_fingerprints, collate, finding_from_dict,
    finding_to_dict, parse_reviewer_result, render_report,
)
from scripts.discovery import (  # noqa: E402
    available_reviewers, discover_strategies,
)
from scripts.exceptions import load_allowed_exceptions  # noqa: E402
from scripts.matching import match  # noqa: E402
from scripts.reconcile import reconcile  # noqa: E402
from scripts.strictness import load_decisions  # noqa: E402

_REVIEWERS_DIR = _ROOT / "skills" / "reviewers"
_STRATEGIES_DIR = _ROOT / "skills" / "strategies"
_DEFAULT_CONFIG = ".review-panel/config.yml"


class CliError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")


def _read_json(path: str):
    try:
        return json.loads(Path(path).read_text())
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise CliError(f"{path} is not valid JSON: {exc}") from exc


def _load_findings(path: str):
    """(findings, clean_files, notes) from a payload list or flat findings."""
    data = _read_json(path)
    if isinstance(data, dict) and "reviewer" not in data and (
        isinstance(data.get("findings"), list) or "agreed" in data
    ):
        # `parse` / `match` output: flat findings, each naming its reviewer.
        flat = data.get("findings")
        if not isinstance(flat, list):
            flat = [r for k in ("agreed", "only_a", "only_b") for r in data.get(k) or []]
        trusted = True  # our own output: fingerprints and verdicts stand
        by_reviewer: dict[str, list] = {}
        skipped: list[str] = []
        for i, raw in enumerate(flat):
            if not isinstance(raw, dict):
                skipped.append(f"REJECTED {i}: not an object")
            elif not raw.get("reviewer"):
                skipped.append(f"REJECTED {raw.get('id', i)}: missing reviewer")
            else:
                by_reviewer.setdefault(str(raw["reviewer"]), []).append(raw)
        payloads = [{"reviewer": r, "findings": fs} for r, fs in by_reviewer.items()]
        extra_clean = _as_list(data.get("clean_files"))
        extra_notes = _as_list(data.get("notes")) + skipped
    else:
        trusted = False
        payloads = data if isinstance(data, list) else [data]
        extra_clean, extra_notes = [], []
    findings, clean, notes = [], list(extra_clean), list(extra_notes)
    for payload in payloads:
        if not isinstance(payload, dict):
            notes.append("REJECTED payload: not an object")
            continue
        try:
            fs, cl, nt = parse_reviewer_result(payload, trusted=trusted)
        except ContractError as exc:
            notes.append(f"REJECTED payload: {exc}")
            continue
        findings += fs
        clean += cl
        notes += nt
    return assign_fingerprints(findings), clean, notes


def _review_dict(review) -> dict:
    d = asdict(review)
    d["targets"] = list(d["targets"])
    d["context"] = list(d["context"])
    return d


def cmd_resolve(args) -> int:
    reviewers_dir = Path(args.reviewers_dir)
    if args.list == "reviewers":
        _emit({"status": "ok", "reviewers": available_reviewers(reviewers_dir)})
        return 0
    if args.list == "strategies":
        _emit({"status": "ok", "strategies": discover_strategies(Path(args.strategies_dir))})
        return 0
    path = Path(args.config)
    if not path.exists():
        _emit({"status": "config-missing", "config": args.config})
        return 3
    try:
        config = load_config(path)
        review = (resolve_adhoc(config, args.reviewer) if args.reviewer
                  else resolve_profile(config, args.profile))
        if args.scope:
            review = replace(review, scope=args.scope)
        if args.output:
            review = replace(review, output=args.output)
    except ConfigError as exc:
        _emit({"status": "error", "error": str(exc)})
        return 1
    _emit({"status": "ok", "review": _review_dict(review)})
    return 0


def cmd_parse(args) -> int:
    findings, clean, notes = _load_findings(args.findings)
    _emit({"status": "ok", "findings": [finding_to_dict(f) for f in findings],
           "clean_files": clean, "notes": notes})
    return 0


def cmd_match(args) -> int:
    a, _, notes_a = _load_findings(args.a)
    b, _, notes_b = _load_findings(args.b)
    result = match(a, b, window=args.window)
    # Fingerprints were assigned per pass; re-assign across the union so a
    # finding only B raised cannot share a key with one only A raised.
    flat = result.agreed + result.only_a + result.only_b
    flat = assign_fingerprints([_unfingerprint(f) for f in flat])
    n1, n2 = len(result.agreed), len(result.agreed) + len(result.only_a)
    _emit({
        "status": "ok",
        "agreed": [finding_to_dict(f) for f in flat[:n1]],
        "only_a": [finding_to_dict(f) for f in flat[n1:n2]],
        "only_b": [finding_to_dict(f) for f in flat[n2:]],
        "notes": [f"A: {n}" for n in notes_a] + [f"B: {n}" for n in notes_b],
    })
    return 0


def _unfingerprint(f):
    return replace(f, fingerprint=None)


def _strictness_map(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        name, sep, level = item.partition("=")
        if not sep or not name or level not in VALID_STRICTNESS:
            raise CliError(f"--strictness wants REVIEWER=LEVEL with LEVEL in "
                           f"{sorted(VALID_STRICTNESS)}, got {item!r}")
        out[name] = level
    return out


def cmd_reconcile(args) -> int:
    findings, clean, notes = _load_findings(args.findings)
    verdicts = None
    if args.verdicts and Path(args.verdicts).exists():
        verdicts = _read_json(args.verdicts)
        if not isinstance(verdicts, dict):
            raise CliError(f"{args.verdicts} must be a JSON object keyed by fingerprint")
    decisions = load_decisions(Path(args.decisions)) if args.decisions else {}
    strictness = _strictness_map(args.strictness)
    warnings: list[str] = []
    reviewers = sorted({f.reviewer for f in findings})
    exceptions = load_allowed_exceptions(Path(args.reviewers_dir), reviewers, warnings)
    result = reconcile(
        findings,
        require_verdicts=args.require_verdicts,
        strictness=strictness,
        exceptions=exceptions,
        decisions=decisions,
        verdicts=verdicts,
    )
    all_notes = notes + warnings + result.notes
    counts = {s: sum(1 for f in result.findings if f.severity == s) for s in VALID_SEVERITY}
    counts["refuted"] = len(result.dropped)
    counts["unverified"] = sum(1 for n in all_notes if n.startswith("unverified:"))
    out = {
        "status": "ok",
        "findings": [finding_to_dict(f) for f in result.findings],
        "dropped": [finding_to_dict(f) for f in result.dropped],
        "clean_files": clean,
        "notes": all_notes,
        "counts": counts,
    }
    if args.out:
        # A scratch file the orchestrator made (mktemp); not a repo path.
        Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    _emit(out)
    return 0


def _safe_relative(path: str) -> Path:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise CliError(f"output path must be relative and inside the repo, got {path!r}")
    return p


def _write_text(path: str, text: str) -> None:
    p = _safe_relative(path)
    cwd = Path.cwd().resolve()
    parent = (cwd / p).parent.resolve()  # follows symlinks
    if parent != cwd and cwd not in parent.parents:
        raise CliError(f"output path resolves outside the repo: {path!r}")
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / p.name
    if target.is_symlink():
        raise CliError(f"output path is a symlink: {path!r}")
    target.write_text(text)


def cmd_report(args) -> int:
    data = _read_json(args.reconciled)
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise CliError(f"{args.reconciled} is not reconcile output")
    findings = [finding_from_dict(d) for d in data["findings"]]
    dropped = [finding_from_dict(d) for d in data.get("dropped") or []]
    text = render_report(
        collate(findings),
        {"strategy": args.strategy, "scope": args.scope, "notes": data.get("notes") or []},
        dropped,
    )
    if args.out:  # the repo-relative output.file from the config
        _write_text(args.out, text)
    sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli.py", description="review-panel deterministic steps")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("resolve", help="resolve a profile or ad-hoc reviewers")
    r.add_argument("--config", default=_DEFAULT_CONFIG)
    r.add_argument("--profile")
    r.add_argument("--reviewer", action="append")
    r.add_argument("--scope", choices=sorted(VALID_SCOPE))
    r.add_argument("--output", choices=sorted(VALID_OUTPUT))
    r.add_argument("--list", choices=["reviewers", "strategies"])
    r.add_argument("--reviewers-dir", default=str(_REVIEWERS_DIR))
    r.add_argument("--strategies-dir", default=str(_STRATEGIES_DIR))
    r.set_defaults(fn=cmd_resolve)

    pa = sub.add_parser("parse", help="reviewer payloads -> fingerprinted findings")
    pa.add_argument("--findings", required=True)
    pa.set_defaults(fn=cmd_parse)

    m = sub.add_parser("match", help="pair two passes' findings")
    m.add_argument("--a", required=True)
    m.add_argument("--b", required=True)
    m.add_argument("--window", type=int, default=3)
    m.set_defaults(fn=cmd_match)

    rc = sub.add_parser("reconcile", help="verdicts, strictness, decisions")
    rc.add_argument("--findings", required=True)
    rc.add_argument("--verdicts")
    rc.add_argument("--require-verdicts", action="store_true")
    rc.add_argument("--strictness", action="append")
    rc.add_argument("--decisions")
    rc.add_argument("--reviewers-dir", default=str(_REVIEWERS_DIR))
    rc.add_argument("--out")
    rc.set_defaults(fn=cmd_reconcile)

    rp = sub.add_parser("report", help="render the markdown report")
    rp.add_argument("--reconciled", required=True)
    rp.add_argument("--strategy", default="?")
    rp.add_argument("--scope", default="?")
    rp.add_argument("--out")
    rp.set_defaults(fn=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except CliError as exc:
        _emit({"status": "error", "error": str(exc)})
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
