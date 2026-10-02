"""Handover notes: validate the agent's structured notes, assemble the document.

The notes follow templates/handover.md (structure adapted from Andrew OE's
handover-work skill). Two sections are mandatory because they are what a fresh
session cannot reconstruct: Failed Attempts (dead ends cost the most context to
rediscover) and a single Next Step (a list invites the next session to re-plan).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from context_vigil import paths, snapshot

SECTIONS = ("Goal", "Current State", "Files in Flight", "Failed Attempts", "Next Step")
REQUIRED = ("Failed Attempts", "Next Step")
RESUME_PREAMBLE = (
    "Resume from this handover. Don't re-investigate anything marked complete, "
    "don't retry anything under Failed Attempts — start with the Next Step."
)

_HEADING = re.compile(r"^##\s+(.*)$")
_NON_WORD = re.compile(r"[^a-z ]")
_CANON = {s.lower(): s for s in SECTIONS}
_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
_PLACEHOLDER = re.compile(r"^<.*>$", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


class HandoverError(ValueError):
    """Notes that cannot become a handover; the message says exactly why."""


def template_path() -> Path:
    return paths.skill_dir() / "templates" / "handover.md"


def _canonical(heading: str) -> Optional[str]:
    key = " ".join(_NON_WORD.sub(" ", heading.lower()).split())
    return _CANON.get(key)


def parse_sections(notes: str) -> Dict[str, str]:
    """Map canonical section name → stripped body, ignoring emoji and case."""
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in _COMMENT.sub("", notes).splitlines():
        match = _HEADING.match(line)
        if match:
            current = _canonical(match.group(1))
            if current is not None:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def validate(notes: str) -> None:
    sections = parse_sections(notes)
    for name in REQUIRED:
        body = sections.get(name, "")
        if not body or _PLACEHOLDER.match(body):
            raise HandoverError(
                f"'## {name}' is missing or empty — "
                + ("write 'None' if nothing failed" if name == "Failed Attempts"
                   else "give exactly one concrete action")
            )
    step = sections["Next Step"]
    items = [line for line in step.splitlines() if _ITEM.match(line)]
    paragraphs = [p for p in re.split(r"\n\s*\n", step) if p.strip()]
    if len(items) > 1 or (not items and len(paragraphs) > 1):
        raise HandoverError("'## Next Step' must hold exactly one action, not a list")


def summary(document: str, written_at: Optional[float]) -> str:
    """One line for the launch notice: when, branch, goal."""
    when = datetime.fromtimestamp(written_at).strftime("%a %H:%M") if written_at else "earlier"
    branch = re.search(r"- Branch: `([^`]+)`", document)
    goal = parse_sections(document).get("Goal", "").splitlines()
    text = f"a handover is waiting from {when}"
    if branch:
        text += f" on `{branch.group(1)}`"
    if goal and goal[0].strip():
        text += f": \"{goal[0].strip()[:80]}\""
    return text


def assemble(notes: str, cwd: Path, inline: List[Path], include_snapshot: bool) -> str:
    validate(notes)
    parts = [f"# Handover — {datetime.now().strftime('%Y-%m-%d %H:%M')}", notes.strip()]
    if include_snapshot:
        parts.append(snapshot.session_snapshot(cwd.resolve()).strip())
    for path in inline:
        try:
            body = path.read_text().strip()
        except OSError as exc:
            raise HandoverError(f"--inline unreadable: {path}: {exc}") from exc
        parts.append(f"## Inlined: `{path}`\n\n```\n{body}\n```")
    return "\n\n".join(parts) + "\n"
