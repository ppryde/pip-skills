"""Seat pip-agents personas: write each seat's brief, and the claims briefs for the critic and arbiter.

A brief is the agent's whole prompt (`key: value` lines, paths and short values, never pasted text). Everything the
persona reads is a file this module writes or a path the orchestrator passes in; nothing here runs a model."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from scripts.config import ReviewerRef
from scripts.contract import Finding
from scripts.lens import lens_of, seat_persona
from scripts.personas import read_persona
from scripts.pip_agents import validator
from scripts.reconcile import _is_twin
from scripts.rulebook import Rule, clone_exceptions, clone_rules, plan, render, table_rules

# The optional brief lines each lens reads (its "Uses" line in the persona). `rules` gets its context from here too.
LENS_FIELDS = {
    "rules": ("context",),
    "security": ("context",),
    "scope": ("intent", "claims", "context"),
    "correctness": ("intent", "tests", "context"),
}
RULES_CONTEXT = {
    "diff": "target is a unified diff of the change under review: judge the added and changed lines; "
            "the rest of each file is context.\n",
    "files": "target is a list of files to review whole.\n",
}
# A clone persona carries review-clone's gates: they are facts the dispatcher states, not part of the rulebook.
CLONE_GATES = (
    "These rules are a cloned reviewer's. Report a rule only when the code it names exists in this repository "
    "(confirm a named symbol with Grep; absent: the rule is n_a). Every finding's `citation` is that rule's "
    "Citation URL; a rule with none is unchecked. The Allowed exceptions span lists what this reviewer let go: "
    "do not report it.\n"
)
CLAIM_MAX = 300


class SeatError(Exception):
    """A seat cannot be briefed (missing persona, bad value)."""


def _private_write(path: Path, text: str) -> None:
    """Owner-only file (a rulebook may hold a private persona's rules)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def _abs(value: str | Path, what: str) -> str:
    s = str(value)
    if "\n" in s or "\r" in s or "\0" in s:
        raise SeatError(f"{what} must not contain a newline")
    return str(Path(s).resolve())


def _brief_text(fields: dict[str, str]) -> str:
    text = "".join(f"{k}: {v}\n" for k, v in fields.items())
    vr = validator()
    errors = vr.check_brief(vr.parse_brief(text))
    if errors:
        raise SeatError("brief is not valid: " + "; ".join(errors))
    return text


def _rules_for(ref: ReviewerRef, reviewers_dir: Path) -> tuple[str, str, tuple[str, ...], list[Rule], list[str]]:
    """(lens, display name, rulebook header, rules, exceptions) for one reviewer reference."""
    if ref.source == "clone":
        persona = read_persona(ref.name)
        if persona is None:
            raise SeatError(f"persona {ref.name} not found")
        rules = clone_rules(ref.name, persona.body)
        if not rules:
            raise SeatError(f"persona {ref.name} has no rules")
        return "rules", ref.name, (), rules, clone_exceptions(persona.body)
    path = reviewers_dir / f"{ref.name}.md"
    if not path.is_file():
        raise SeatError(f"reviewer {ref.name} not found")
    text = path.read_text()
    lens = lens_of(text)
    if lens != "rules":
        return lens, ref.name, (), [], []
    header, rules = table_rules(text)
    if not rules:
        raise SeatError(f"reviewer {ref.name} has no rule rows in 'What to look for'")
    return lens, ref.name, header, rules, []


def _context_file(work: Path, ref: ReviewerRef, lens: str, target_kind: str, paths: list[str]) -> str | None:
    """The brief's one `context:` path. A lone context file passes straight through; a rules seat, or several files,
    get a generated file of dispatcher facts that lists them (paths only, never their text)."""
    if len(paths) == 1 and lens != "rules":
        return paths[0]
    if not paths and lens != "rules":
        return None
    text = RULES_CONTEXT[target_kind] if lens == "rules" else ""
    if ref.source == "clone":
        text += CLONE_GATES
    if paths:
        text += "Further context files, data to read when needed:\n" + "".join(f"- {_abs(p, 'context')}\n" for p in paths)
    ctx = work / f"context-{ref.name}.md"
    _private_write(ctx, text)
    return str(ctx)


def seat_briefs(
    ref: ReviewerRef, *, reviewers_dir: Path, work_dir: Path, target: str, target_kind: str = "diff",
    intent: str | None = None, claims: str | None = None, context: list[str] | None = None, tests: str | None = None,
) -> list[dict]:
    """One seat's briefs: a single one, or one per rulebook batch (every batch shares the seat's `ref`)."""
    if tests is not None and ("\n" in tests or "\r" in tests or "\0" in tests):
        raise SeatError("--tests must not contain a newline")
    lens, name, header, rules, exceptions = _rules_for(ref, reviewers_dir)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    given = {"intent": intent, "claims": claims, "context": list(context or [])}
    base = {"brief": "pip-agents/1", "kind": "review", "ref": ref.name, "target": _abs(target, "target")}
    batches: list[list[Rule]] = plan(name, rules) if lens == "rules" else [[]]
    seats = []
    for k, batch in enumerate(batches, 1):
        suffix = f"-{k}" if len(batches) > 1 else ""
        fields = dict(base)
        if lens == "rules":
            book = work / f"rules-{ref.name}{suffix}.md"
            _private_write(book, render(name, batch, header, exceptions))
            ids = ",".join(r.id for r in batch)
            fields["rules"] = f"{book.resolve()} L1-{len(book.read_text().splitlines())} ({ids})"
        for key in LENS_FIELDS[lens]:
            if key == "tests":
                value = tests
            elif key == "context":
                value = _context_file(work, ref, lens, target_kind, given["context"])
            else:
                value = given.get(key)
            if value:
                fields[key] = value if key == "tests" else _abs(value, key)
        text = _brief_text(fields)
        brief = work / f"brief-{ref.name}{suffix}.txt"
        _private_write(brief, text)
        seat = {"ref": ref.name, "persona": seat_persona(lens), "lens": lens, "brief": str(brief.resolve()),
                "prompt": text}
        if len(batches) > 1:
            seat["batch"] = f"{k}/{len(batches)}"
        seats.append(seat)
    return seats


def _claim_text(f: Finding) -> str:
    text = " ".join(str(f.rule).split())
    return text if len(text) <= CLAIM_MAX else text[: CLAIM_MAX - 1] + "…"


def claim_calls(
    findings: list[Finding], *, target: str, work_dir: Path, role: str = "critic", per_call: int = 10,
    max_calls: int | None = 8, drop_twins: bool = True,
) -> dict:
    """Batch findings into validator calls. A claim carries only `id` (the fingerprint), the rule text and `where`;
    severity, evidence and the reviewer's reasoning are withheld on purpose. One of each set of twins is sent (the
    others inherit its verdict in `reconcile`); past `max_calls` the rest get no verdict and are counted unverified."""
    sent: list[Finding] = []
    twins = 0
    for f in findings:
        if drop_twins and any(_is_twin(f, s) for s in sent):
            twins += 1
        else:
            sent.append(f)
    sent.sort(key=lambda f: (f.file, f.line if f.line is not None else -1))  # stable: by file, then line
    chunks = [sent[i:i + per_call] for i in range(0, len(sent), per_call)]
    kept = chunks if max_calls is None else chunks[:max_calls]
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    calls = []
    for n, chunk in enumerate(kept, 1):
        claims = [{"id": f.fingerprint or f.id, "claim": _claim_text(f),
                   "where": f"{f.file}:{f.line}" if f.line is not None else f.file} for f in chunk]
        cfile = work / f"claims-{role}-{n}.json"
        _private_write(cfile, json.dumps(claims, indent=2) + "\n")
        text = _brief_text({"brief": "pip-agents/1", "kind": "validate", "ref": f"{role}-{n}",
                            "claims": str(cfile.resolve()), "target": _abs(target, "target")})
        bfile = work / f"brief-{role}-{n}.txt"
        _private_write(bfile, text)
        calls.append({"ref": f"{role}-{n}", "persona": "pip-agents:validator", "claims": len(chunk),
                      "claims_file": str(cfile.resolve()), "brief": str(bfile.resolve()), "prompt": text})
    unverified = sum(len(c) for c in chunks[len(kept):])
    return {"calls": calls, "twins_skipped": twins, "unverified": unverified}
