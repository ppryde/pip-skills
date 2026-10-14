"""dispatch-prep: compose one agent's bundle file (WF-113 §5.3).

The orchestrator used to spend ~5 full-context turns per dispatch fetching
calibration and facts, writing a diff, gathering prior findings and filling
a template — often pasting the result into the prompt. This does all of it
in one CLI call and prints a path; the agent's whole prompt is that path.

``--var`` values are capped (VAR_CAP): anything longer belongs in a file,
which makes pasting a plan, diff or findings list through here impossible.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts import gitops
from scripts.calibration import BANDS, calibrate
from scripts.dispatch import dispatch_dir
from scripts import db
from scripts.knowledge import load_facts
from scripts.models import Card

VAR_CAP = 300
TERSE_CHARTER = (
    "**Voice:** terse and factual. State results, not process. No preamble, no recap, "
    "no narration of what you are about to do. Expand only when asked."
)
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
CLI_PATH = Path(__file__).resolve().parent / "cli.py"
KNOWN_PLACEHOLDERS = (
    "card_id", "title", "stage", "round_no", "slot", "chunk_no", "goal", "complexity",
    "worktree", "reply_path", "cli", "knowledge", "calibration", "charter", "lens",
    "target_path", "prior_findings", "verdict_paths", "gate_commands", "constraints",
    "repo_context", "target_note", "plan_fix",
)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_VAR_KEY = re.compile(r"\A\w+\Z")
_ROUND_FILE = re.compile(r"\Ar(\d+)-[A-Za-z0-9]+\.md\Z")
MAX_FACTS = 8  # default; repo config `knowledge_max` overrides
# Roles whose bundle carries no knowledge unless the orchestrator asks (`--var knowledge=1`):
# the fixer acts on named findings, not on repo lore. (The verifier template has no
# `{{knowledge}}` slot at all, so it never carries facts and is not listed.)
KNOWLEDGE_ON_REQUEST = ("fixer",)


class BundleError(ValueError):
    """dispatch-prep was asked for a bundle it cannot build."""


def parse_vars(pairs: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not _VAR_KEY.match(key):
            raise BundleError(f"--var {pair!r} must be key=value")
        if len(value) > VAR_CAP:
            raise BundleError(
                f"--var {key} is {len(value)} chars (cap {VAR_CAP}): write it to a file "
                "and pass the path instead"
            )
        values[key] = value
    return values


def reply_name(role: str, *, round_no: int, slot: str | None, chunk: int | None) -> str:
    if role == "reviewer":
        if not slot:
            raise BundleError("--slot is required for a reviewer")
        if slot == "fix":
            raise BundleError("slot 'fix' is reserved for the fixer's report")
        return f"r{round_no}-{slot}.md"
    if role == "fixer":
        return f"r{round_no}-fix.md"
    if role == "implementer":
        if chunk is None:
            raise BundleError("--chunk is required for an implementer")
        return f"c{chunk}.md"
    if role == "planner":
        return "plan.md"
    if role == "verifier":
        return "verification.md"
    raise BundleError(f"unknown role {role!r}")


def _bundle_name(role: str, *, round_no: int, slot: str | None, chunk: int | None) -> str:
    tag = slot if role == "reviewer" else (f"c{chunk}" if role == "implementer" else None)
    return f"bundle-{role}{'-' + tag if tag else ''}-r{round_no}.md"


def _bullets(paths: list[Path]) -> str:
    return "\n".join(f"  - {p}" for p in paths) if paths else "_(none)_"


def _files_for_rounds(directory: Path, rounds: set[int], *, include_fix: bool) -> list[Path]:
    found = []
    for path in sorted(directory.glob("r*-*.md")):
        match = _ROUND_FILE.match(path.name)
        if not match or int(match.group(1)) not in rounds:
            continue
        if path.name.endswith("-fix.md") and not include_fix:
            continue
        found.append(path)
    return found


def _knowledge(repo_root: Path, card: Card, today: str, limit: int = MAX_FACTS) -> str:
    if not card.labels:
        return "_(none)_"
    conn = db.connect(repo_root, migrate=False)
    try:
        facts, _ = load_facts(conn)
    finally:
        conn.close()
    lines = []
    for fact in facts:
        if not set(fact.tags) & set(card.labels):
            continue
        stale = " [STALE — verify first]" if fact.effective_status(today) == "stale" else ""
        lines.append(f"  - {fact.id}{stale}: {fact.statement}")
    return "\n".join(lines[:limit]) or "_(none)_"


def _calibration(archived: list[Card]) -> str:
    report = calibrate(archived)
    parts = []
    for band in BANDS:
        data = report["bands"][band]
        if data["count"]:
            parts.append(f"{band} n={data['count']} median ×{data['median']}")
    return "; ".join(parts) or "_(no samples)_"


@dataclass(frozen=True)
class BundleSpec:
    """Everything ``render`` needs from the board, as plain strings: a ``--remote``
    client gets it from ``dispatch-record`` and renders in its own container, so
    no host path is in it (``worktree`` is None until the card has one)."""

    card_id: str
    title: str
    complexity: str | None
    goal: str | None
    plan: str
    worktree: str | None
    stage: str
    role: str
    round_no: int
    slot: str | None
    chunk: int | None
    lens: str | None
    verbosity: str
    knowledge: str
    calibration: str


def spec_from_record(
    record: dict, *, stage: str, role: str, round_no: int, slot: str | None, lens: str | None,
) -> BundleSpec:
    """A ``BundleSpec`` from one ``dispatch-record`` JSON record and one of its slots."""
    card = record["card"]
    return BundleSpec(
        card_id=card["id"], title=card["title"], complexity=card["complexity"],
        goal=card["goal"], plan=card["plan"], worktree=card["worktree"], stage=stage,
        role=role, round_no=round_no, slot=slot, chunk=record["chunk"], lens=lens,
        verbosity=record["verbosity"], knowledge=record["knowledge"],
        calibration=record["calibration"],
    )


def prepare(
    repo_root: Path,
    card: Card,
    *,
    stage: str,
    role: str,
    round_no: int,
    slot: str | None,
    chunk: int | None,
    lens: str | None,
    variables: dict[str, str],
    verbosity: str,
    knowledge_max: int = MAX_FACTS,
    archived: list[Card],
    today: str,
) -> Path:
    """Load the board-derived parts, take the review diff when one is due, and
    ``render``. The local path; a remote client does the same from a record."""
    reply_name(role, round_no=round_no, slot=slot, chunk=chunk)
    spec = BundleSpec(
        card_id=card.id, title=card.title, complexity=card.complexity,
        goal=card.sections.get("## Goal"), plan=card.sections.get("## Plan", ""),
        worktree=card.worktree, stage=stage, role=role,
        round_no=round_no, slot=slot, chunk=chunk, lens=lens, verbosity=verbosity,
        knowledge=_knowledge(repo_root, card, today, knowledge_max),
        calibration=_calibration(archived) if role == "planner" else "",
    )
    diff_text = None
    if role == "reviewer" and stage != "plan-review":
        worktree = Path(card.worktree) if card.worktree else repo_root
        try:
            review = gitops.review_diff(worktree)
        except gitops.GitError as exc:
            raise BundleError(f"could not write the diff: {exc}") from exc
        diff_text = review.text
        for warning in review.warnings:
            print(f"dispatch-prep: {warning}", file=sys.stderr)
    return render(spec, diff_text, dispatch_dir(repo_root, card.id, stage),
                  f"{sys.executable} {CLI_PATH} --root {repo_root}", repo_root, variables)


def render(
    spec: BundleSpec,
    diff_text: str | None,
    directory: Path,
    cli: str,
    repo_root: Path,
    variables: dict[str, str],
) -> Path:
    """Write the bundle (and the reviewer's plan snapshot or diff) into
    ``directory``. Pure of the board and of git: ``repo_root`` only stands in for
    a card with no worktree yet."""
    role, stage, round_no, slot, chunk = spec.role, spec.stage, spec.round_no, spec.slot, spec.chunk
    reply = reply_name(role, round_no=round_no, slot=slot, chunk=chunk)
    directory.mkdir(parents=True, exist_ok=True)
    worktree = Path(spec.worktree) if spec.worktree else repo_root
    values: dict[str, str] = {
        "card_id": spec.card_id,
        "title": spec.title,
        "stage": stage,
        "round_no": str(round_no),
        "slot": slot or "",
        "chunk_no": "" if chunk is None else str(chunk),
        "goal": spec.goal or "_(none)_",
        "complexity": spec.complexity or "_(ungraded)_",
        "worktree": str(worktree),
        "reply_path": str(directory / reply),
        "cli": cli,
        "knowledge": spec.knowledge,
        "calibration": spec.calibration,
        "charter": "" if spec.verbosity == "normal" else TERSE_CHARTER,
        "lens": spec.lens or "general",
        "prior_findings": _bullets(
            _files_for_rounds(directory, set(range(1, round_no)), include_fix=True)
        ),
        "target_note": "",
        "plan_fix": "",
        "verdict_paths": _bullets(_files_for_rounds(directory, {round_no}, include_fix=False)),
    }
    if role == "reviewer":
        if stage == "plan-review":
            target = directory / "plan.snapshot.md"
            target.write_text(spec.plan)
            values["target_note"] = " (a read-only snapshot of the card's ## Plan; do not edit it)"
        else:
            target = directory / "diff.patch"
            target.write_text(diff_text or "")
        values["target_path"] = str(target)
    if role == "fixer" and stage == "plan-review":
        # The reviewers read a snapshot taken from the card's ## Plan at dispatch time,
        # so a fix applied to the snapshot file never reaches the next round (WF-288).
        values["plan_fix"] = (
            "\n- Plan fixes: the plan is the card's `## Plan` section; `plan.snapshot.md` in the "
            "dispatch folder is a read-only view for reviewers and editing it fixes nothing. "
            "Read the CURRENT plan first with "
            f"`{values['cli']} show {spec.card_id} --section Plan` (it may have been edited since "
            "dispatch; never build on the snapshot) and apply your fixes on top of it. "
            "Write the corrected full plan to a temp file, then run "
            f"`{values['cli']} set-section {spec.card_id} --section Plan --text-file <file>`; "
            "the next round's snapshot is taken from it."
        )
    if role in KNOWLEDGE_ON_REQUEST:
        # Opt in with `--var knowledge=1`; otherwise the bundle carries no facts.
        if variables.pop("knowledge", "") != "1":
            values["knowledge"] = "_(none)_"
    clash = sorted(set(variables) & set(values))
    if clash:
        raise BundleError(f"--var cannot override built-in placeholder(s): {', '.join(clash)}")
    values.update(variables)
    template = (TEMPLATES_DIR / f"{role}.md").read_text()
    text = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), "_(none)_"), template)
    path = directory / _bundle_name(role, round_no=round_no, slot=slot, chunk=chunk)
    path.write_text(text)
    return path
