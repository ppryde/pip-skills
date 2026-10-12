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
               | --args TOKEN...   the /review-panel words, one precedence:
                 reserved words (reviewers strategies full interactive inline),
                 then a profile name, then reviewer keys; anything else is an
                 error listing the valid values. Ad-hoc reviewers run on
                 defaults when the config file is absent.
             stdout {"status":"ok","review":{strategy,scope,targets,reviewers:
             [{key,source,name,strictness}],context,output,output_file}}
             {"status":"config-missing"} exit 3 when the config file is absent;
             {"status":"error","error":...} exit 1 on a bad config/request.

  brief      one reviewer key -> the brief(s) for its pip-agents persona
               --reviewer KEY --target FILE --work-dir DIR [--target-kind diff|files]
               [--intent FILE] [--claims FILE] [--context FILE ...] [--tests CMD]
             KEY is a builtin name or clone:<alias>. The lens (`lens:` in the
             reviewer file's frontmatter, default `rules`) picks the persona. A rules
             seat gets a generated rulebook file (0600) of at most 30 rules, so a bigger
             book is several seats sharing one `ref`. Briefs hold paths only.
             stdout {"status":"ok","seats":[{ref,persona,lens,brief,prompt[,batch]}]}
             {"status":"error","error":...} exit 1 (unknown reviewer, missing persona).

  ingest     a seat's final message -> validated, adapted, appended to --out
               --brief FILE --message FILE --persona NAME --out FILE
             Validates the ```pip-agents-result block with the vendored pip-agents
             validator (rejected whole, never repaired). A review seat appends its
             reviewer payload to --out (a JSON list); a validator merges its verdicts
             into --out (a JSON object keyed by claim id = fingerprint).
             stdout {"status":"ok","kind",...,"seat_error","injection_attempts"};
             {"status":"rejected","errors":[...]} exit 1, nothing written.

  claims     findings -> validator briefs (critic, or arbiter with --disputed)
               --findings FILE --target FILE --out-dir DIR [--disputed]
               [--per-call 10] [--max-calls 8]
             FILE: `parse` output (or `match` output with --disputed). Sends one of
             each set of twins; a claim is {id, claim, where} with severity, evidence
             and reasoning withheld. stdout {"status":"ok","calls":[{ref,persona,
             claims,claims_file,brief,prompt}],"twins_skipped":n,"unverified":n}.

  parse      reviewer payloads -> findings with fingerprints
               --findings FILE
             FILE: a JSON list of reviewer payloads (or one payload).
             stdout {"status":"ok","findings":[...],"clean_files":[...],"notes":[...]}
             Notes carry `REJECTED <id>: <reason>` for malformed findings.
             NO findings file is ever trusted (parse, match and reconcile
             alike): verdict, reason, severity_before, fingerprint,
             category_defaulted and `_source` in input are ignored, and
             fingerprints are always recomputed in code. Verdicts come only
             from `reconcile --verdicts`. The output (flat findings) may be
             fed to `reconcile --findings` (it is re-read as plain data, so
             `category_defaulted` is dropped). `match` takes the RAW reviewer
             payloads only: its category-defaulted guard needs them.

  match      two independent passes -> agreed / disagreements (dual-tiebreaker)
               --a FILE --b FILE [--window 3]
             stdout {"status":"ok","findings":[all],"agreed":[...],
             "only_a":[...],"only_b":[...],"verdicts":{<fp>: confirmed for
             each agreed finding},"notes":[...]}; fingerprints are final
             across all lists, and are the ones `reconcile` recomputes from
             this file. Merge "verdicts" with the arbiter's into --verdicts.

  reconcile  verdicts -> strictness -> decisions
               --findings FILE [--verdicts FILE] [--require-verdicts]
               [--strictness REVIEWER=LEVEL ...] [--decisions FILE]
               [--reviewers-dir DIR] [--out FILE]
             --findings: reviewer payloads, or the flat `parse`/`match`
             output (all of its findings are reconciled together).
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

import yaml

_ROOT = Path(__file__).resolve().parent.parent
# Imports below resolve `scripts.*` against this plugin whatever the cwd or
# PYTHONPATH is. Drop this file's own directory so a stray sibling module can
# never shadow a stdlib name.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(_ROOT))

from scripts.arguments import parse_arguments  # noqa: E402
from scripts.config import (  # noqa: E402
    VALID_OUTPUT, VALID_SCOPE, VALID_STRICTNESS,
    ConfigError, load_config, parse_reviewer_key, resolve_adhoc, resolve_profile,
)
from scripts.contract import (  # noqa: E402
    VALID_SEVERITY, ContractError, _as_list, assign_fingerprints, collate, finding_from_dict,
    finding_to_dict, parse_reviewer_result, render_report,
)
from scripts.discovery import (  # noqa: E402
    available_reviewers, discover_strategies,
)
from scripts.exceptions import load_allowed_exceptions  # noqa: E402
from scripts.lens import LensError  # noqa: E402
from scripts.matching import match  # noqa: E402
from scripts.envelope import ingest  # noqa: E402
from scripts.reconcile import reconcile  # noqa: E402
from scripts.seats import SeatError, claim_calls, seat_briefs  # noqa: E402
from scripts.strictness import load_decisions  # noqa: E402

_REVIEWERS_DIR = _ROOT / "skills" / "reviewers"
_STRATEGIES_DIR = _ROOT / "skills" / "strategies"
_DEFAULT_CONFIG = ".review-panel/config.yml"
_MAX_MESSAGE_BYTES = 2_000_000


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
    """(findings, clean_files, notes) from a findings file.

    No findings file is ever trusted, whatever it contains or however it is
    laid out (reviewer payloads, or the flat output of `parse`/`match`):
    `verdict`, `reason`, `severity_before`, `fingerprint`,
    `category_defaulted` and `_source` are ignored, and fingerprints are always
    recomputed here. Verdicts come only from `--verdicts`."""
    return _findings_from_data(_read_json(path))


def _findings_from_data(data):
    flat_shape = isinstance(data, dict) and "reviewer" not in data and (
        isinstance(data.get("findings"), list) or any(k in data for k in ("agreed", "only_a", "only_b"))
    )
    notes: list[str] = []
    if isinstance(data, dict) and "_source" in data:
        notes.append("ignored _source in input")
    payloads: list = []
    clean: list = []
    if flat_shape:
        # Flat findings (`parse`/`match` output shape), each naming its
        # reviewer. One payload per finding keeps the original order.
        flat = data.get("findings")
        if not isinstance(flat, list):
            flat = []
            for key in ("agreed", "only_a", "only_b"):
                part = data.get(key)
                if part is None:
                    continue
                if not isinstance(part, list):
                    raise CliError(f"{key!r} must be a list, got {type(part).__name__}")
                flat += part
        for i, raw in enumerate(flat):
            if not isinstance(raw, dict):
                notes.append(f"REJECTED {i}: not an object")
            elif not raw.get("reviewer"):
                notes.append(f"REJECTED {raw.get('id', i)}: missing reviewer")
            else:
                payloads.append({"reviewer": raw["reviewer"], "findings": [raw]})
        clean += _as_list(data.get("clean_files"))
        notes += _as_list(data.get("notes"))
    else:
        payloads = data if isinstance(data, list) else [data]
    findings = []
    for payload in payloads:
        if not isinstance(payload, dict):
            notes.append("REJECTED payload: not an object")
            continue
        try:
            fs, cl, nt = parse_reviewer_result(payload)
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
    exists = path.exists()
    try:
        config = load_config(path) if exists else {}
        scope, output = args.scope, args.output
        keys, profile = args.reviewer, args.profile
        if args.args is not None:
            req = parse_arguments(args.args, config, available_reviewers(reviewers_dir),
                                  discover_strategies(Path(args.strategies_dir)))
            if req.list == "reviewers":
                _emit({"status": "ok", "reviewers": available_reviewers(reviewers_dir)})
                return 0
            if req.list == "strategies":
                _emit({"status": "ok",
                       "strategies": discover_strategies(Path(args.strategies_dir))})
                return 0
            keys, profile = list(req.reviewers) or None, req.profile
            scope, output = req.scope or scope, req.output or output
        if not keys and not exists:  # a profile needs the config; ad-hoc runs on defaults
            _emit({"status": "config-missing", "config": args.config})
            return 3
        review = (resolve_adhoc(config, keys, scope=scope, output=output) if keys
                  else resolve_profile(config, profile, scope=scope, output=output))
    except ConfigError as exc:
        if args.args is not None and not exists:
            _emit({"status": "config-missing", "config": args.config, "detail": str(exc)})
            return 3
        _emit({"status": "error", "error": str(exc)})
        return 1
    _emit({"status": "ok", "review": _review_dict(review)})
    return 0


def cmd_parse(args) -> int:
    findings, clean, notes = _load_findings(args.findings)
    _emit({"status": "ok",
           "findings": [finding_to_dict(f) for f in findings],
           "clean_files": clean, "notes": notes})
    return 0


def cmd_match(args) -> int:
    a, _, notes_a = _load_findings(args.a)
    b, _, notes_b = _load_findings(args.b)
    result = match(a, b, window=args.window)
    # Fingerprints are recomputed across the union by the very loader that
    # `reconcile` will use on this output, so the keys here are the keys it
    # will see. (A finding only B raised cannot share a key with one only A
    # raised.)
    union = result.agreed + result.only_a + result.only_b
    flat_dicts = [finding_to_dict(replace(f, fingerprint=None)) for f in union]
    final, _, _ = _findings_from_data({"findings": flat_dicts})
    n1, n2 = len(result.agreed), len(result.agreed) + len(result.only_a)
    dicts = [finding_to_dict(f) for f in final]
    _emit({
        "status": "ok",
        "findings": dicts,
        "agreed": dicts[:n1],
        "only_a": dicts[n1:n2],
        "only_b": dicts[n2:],
        # Verdicts the code itself decided; merge into the arbiter's verdicts
        # file for `reconcile --verdicts` (nothing is read back from this file).
        "verdicts": {f.fingerprint: {"verdict": "confirmed", "reason": "both passes"}
                     for f in final[:n1]},
        "notes": [f"A: {n}" for n in notes_a] + [f"B: {n}" for n in notes_b],
    })
    return 0


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
    elif args.verdicts:
        # Tolerated (a stage may legitimately produce none) but never silent.
        notes.append(f"verdicts file not found, no verdicts applied: {args.verdicts}")
    try:
        decisions = load_decisions(Path(args.decisions)) if args.decisions else {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise CliError(f"cannot read decisions file {args.decisions}: {exc}") from exc
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
        _write_scratch(args.out, json.dumps(out, indent=2) + "\n")
    _emit(out)
    return 0


def cmd_brief(args) -> int:
    try:
        ref = parse_reviewer_key(args.reviewer, "pragmatic")
        seats = seat_briefs(
            ref, reviewers_dir=Path(args.reviewers_dir), work_dir=Path(args.work_dir), target=args.target,
            target_kind=args.target_kind, intent=args.intent, claims=args.claims, context=args.context,
            tests=args.tests,
        )
    except (ConfigError, SeatError, LensError, OSError) as exc:
        _emit({"status": "error", "error": str(exc)})
        return 1
    _emit({"status": "ok", "seats": seats})
    return 0


def _read_text(path: str) -> str:
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > _MAX_MESSAGE_BYTES:
            raise CliError(f"{path} is not a regular file within {_MAX_MESSAGE_BYTES} bytes")
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError(f"cannot read {path}: {exc}") from exc


def cmd_ingest(args) -> int:
    got = ingest(_read_text(args.message), _read_text(args.brief), args.persona)
    if not got.ok:
        _emit({"status": "rejected", "errors": got.errors})
        return 1
    out = Path(args.out)
    shape = list if got.kind == "review" else dict
    existing = shape()
    if out.exists():
        existing = _read_json(args.out)
        if not isinstance(existing, shape):
            raise CliError(f"{args.out} must hold a JSON {shape.__name__} (it holds {type(existing).__name__})")
    if got.kind == "review":
        existing.append(got.payload)
        count = len(got.payload["findings"])
    else:
        existing.update(got.verdicts)
        count = len(got.verdicts)
    _write_scratch(args.out, json.dumps(existing, indent=2) + "\n")
    _emit({"status": "ok", "kind": got.kind, "seat": got.seat, "envelope_status": got.status,
           ("findings" if got.kind == "review" else "verdicts"): count, "seat_error": got.seat_error,
           "injection_attempts": got.injection_attempts, "summary": got.summary})
    return 0


def cmd_claims(args) -> int:
    data = _read_json(args.findings)
    if not isinstance(data, dict):
        raise CliError(f"{args.findings} is not parse/match output")
    raw = (data.get("only_a", []) + data.get("only_b", [])) if args.disputed else data.get("findings", [])
    if not isinstance(raw, list):
        raise CliError(f"{args.findings}: findings must be a list")
    findings = [finding_from_dict(d) for d in raw if isinstance(d, dict)]
    try:
        result = claim_calls(
            findings, target=args.target, work_dir=Path(args.out_dir), role="arbiter" if args.disputed else "critic",
            per_call=args.per_call, max_calls=args.max_calls, drop_twins=not args.disputed,
        )
    except (SeatError, OSError) as exc:
        _emit({"status": "error", "error": str(exc)})
        return 1
    _emit({"status": "ok", **result})
    return 0


def _safe_relative(path: str) -> Path:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise CliError(f"output path must be relative and inside the repo, got {path!r}")
    return p


def _under(parent: Path, root: Path) -> bool:
    return parent == root or root in parent.parents


def _write_confined(p: Path, text: str, roots: list[Path], path: str) -> None:
    """Write `p` only if its parent, symlinks resolved, sits under one of
    `roots`, and the target itself is not a symlink."""
    parent = (Path.cwd() / p).parent.resolve()
    if not any(_under(parent, r) for r in roots):
        raise CliError(f"output path resolves outside the allowed area: {path!r}")
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / p.name
    if target.is_symlink():
        raise CliError(f"output path is a symlink: {path!r}")
    target.write_text(text)


def _write_text(path: str, text: str) -> None:
    """Repo output (report --out): relative, and inside the cwd."""
    _write_confined(_safe_relative(path), text, [Path.cwd().resolve()], path)


def _write_scratch(path: str, text: str) -> None:
    """Scratch output (reconcile --out): inside the cwd or the temp dir."""
    import tempfile
    roots = [Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve()]
    _write_confined(Path(path), text, roots, path)


def _report_finding(d, path: str):
    """A Finding from reconcile output, or a CliError naming the file."""
    try:
        if not isinstance(d, dict):
            raise TypeError("finding is not an object")
        f = finding_from_dict(d)
        if f.severity not in VALID_SEVERITY:
            raise ValueError(f"invalid severity {f.severity!r}")
        if not all(isinstance(getattr(f, k), str) for k in ("reviewer", "id", "file", "rule")):
            raise TypeError("reviewer, id, file and rule must be strings")
        return f
    except (TypeError, ValueError) as exc:
        raise CliError(f"{path} is not reconcile output: {exc}") from exc


def cmd_report(args) -> int:
    data = _read_json(args.reconciled)
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise CliError(f"{args.reconciled} is not reconcile output")
    dropped_raw = data.get("dropped") or []
    if not isinstance(dropped_raw, list):
        raise CliError(f"{args.reconciled} is not reconcile output ('dropped' is not a list)")
    findings = [_report_finding(d, args.reconciled) for d in data["findings"]]
    dropped = [_report_finding(d, args.reconciled) for d in dropped_raw]
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
    r.add_argument("--args", nargs="*", metavar="TOKEN",
                   help="the raw /review-panel argument words (validated here)")
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

    b = sub.add_parser("brief", help="write a seat's brief(s) for its pip-agents persona")
    b.add_argument("--reviewer", required=True, help="a reviewer key: a builtin name or clone:<alias>")
    b.add_argument("--target", required=True, help="the diff file (or a file-list file)")
    b.add_argument("--target-kind", choices=["diff", "files"], default="diff")
    b.add_argument("--work-dir", required=True)
    b.add_argument("--intent")
    b.add_argument("--claims")
    b.add_argument("--context", action="append", help="a context file; repeat for several")
    b.add_argument("--tests", help="the one test command a correctness seat may run, verbatim")
    b.add_argument("--reviewers-dir", default=str(_REVIEWERS_DIR))
    b.set_defaults(fn=cmd_brief)

    ig = sub.add_parser("ingest", help="validate a seat's final message and add it to the findings/verdicts file")
    ig.add_argument("--brief", required=True)
    ig.add_argument("--message", required=True)
    ig.add_argument("--persona", required=True, help="the bare agent name, e.g. reviewer-scope or validator")
    ig.add_argument("--out", required=True)
    ig.set_defaults(fn=cmd_ingest)

    cl = sub.add_parser("claims", help="batch findings into validator briefs (critic or arbiter)")
    cl.add_argument("--findings", required=True, help="`parse` output, or `match` output with --disputed")
    cl.add_argument("--target", required=True, help="the diff file")
    cl.add_argument("--out-dir", required=True)
    cl.add_argument("--disputed", action="store_true", help="arbiter: only `only_a` and `only_b`")
    cl.add_argument("--per-call", type=int, default=10)
    cl.add_argument("--max-calls", type=int, default=8)
    cl.set_defaults(fn=cmd_claims)

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
