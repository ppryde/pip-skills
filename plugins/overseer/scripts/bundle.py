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
from pathlib import Path

from scripts import gitops
from scripts.calibration import BANDS, calibrate
from scripts.dispatch import dispatch_dir
from scripts.knowledge import knowledge_root, load_facts
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
    "repo_context",
)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_VAR_KEY = re.compile(r"\A\w+\Z")
_ROUND_FILE = re.compile(r"\Ar(\d+)-[A-Za-z0-9]+\.md\Z")
MAX_FACTS = 15


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


def _knowledge(repo_root: Path, card: Card, today: str) -> str:
    if not card.labels:
        return "_(none)_"
    facts, _ = load_facts(knowledge_root(repo_root))
    lines = []
    for fact in facts:
        if not set(fact.tags) & set(card.labels):
            continue
        stale = " [STALE — verify first]" if fact.effective_status(today) == "stale" else ""
        lines.append(f"  - {fact.id}{stale}: {fact.statement}")
    return "\n".join(lines[:MAX_FACTS]) or "_(none)_"


def _calibration(archived: list[Card]) -> str:
    report = calibrate(archived)
    parts = []
    for band in BANDS:
        data = report["bands"][band]
        if data["count"]:
            parts.append(f"{band} n={data['count']} median ×{data['median']}")
    return "; ".join(parts) or "_(no samples)_"


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
    archived: list[Card],
    today: str,
) -> Path:
    reply = reply_name(role, round_no=round_no, slot=slot, chunk=chunk)
    directory = dispatch_dir(repo_root, card.id, stage)
    directory.mkdir(parents=True, exist_ok=True)
    worktree = Path(card.worktree) if card.worktree else repo_root
    sections = card.sections
    values: dict[str, str] = {
        "card_id": card.id,
        "title": card.title,
        "stage": stage,
        "round_no": str(round_no),
        "slot": slot or "",
        "chunk_no": "" if chunk is None else str(chunk),
        "goal": sections.get("## Goal") or "_(none)_",
        "complexity": card.complexity or "_(ungraded)_",
        "worktree": str(worktree),
        "reply_path": str(directory / reply),
        "cli": f"{sys.executable} {CLI_PATH} --root {repo_root}",
        "knowledge": _knowledge(repo_root, card, today),
        "calibration": _calibration(archived),
        "charter": "" if verbosity == "normal" else TERSE_CHARTER,
        "lens": lens or "general",
        "prior_findings": _bullets(
            _files_for_rounds(directory, set(range(1, round_no)), include_fix=True)
        ),
        "verdict_paths": _bullets(_files_for_rounds(directory, {round_no}, include_fix=False)),
    }
    if role == "reviewer":
        if stage == "plan-review":
            target = directory / "plan.snapshot.md"
            target.write_text(sections.get("## Plan", ""))
        else:
            target = directory / "diff.patch"
            try:
                target.write_text(gitops.diff_against_base(worktree))
            except gitops.GitError as exc:
                raise BundleError(f"could not write the diff: {exc}") from exc
        values["target_path"] = str(target)
    values.update(variables)
    template = (TEMPLATES_DIR / f"{role}.md").read_text()
    text = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), "_(none)_"), template)
    path = directory / _bundle_name(role, round_no=round_no, slot=slot, chunk=chunk)
    path.write_text(text)
    return path
