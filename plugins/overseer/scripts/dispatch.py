"""Dispatch directory layout and the one-line agent reply grammar (WF-113 §4).

Every overseer agent writes its detail to a file under
``<state_root>/dispatch/<card>/<stage>/`` and ends with ONE line in a fixed
grammar. The parent reads that line to decide what happens next; the
SubagentStop report hook parses the same line into the ledger. Replies carry a
path, never content — that is what keeps the orchestrator's context small.

The file name encodes round/slot/chunk, so the hook needs nothing but the line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.store import state_root

REPLY_WORD_CAP = 25
ROLES = ("planner", "implementer", "reviewer", "fixer", "verifier")

_TO = r"\s*(?:→|->)\s*"
_SHA = r"([0-9a-f]{7,40}|-)"
_GRAMMAR: dict[str, re.Pattern[str]] = {
    "reviewer": re.compile(rf"\A(approved|found wanting) (\d+)C (\d+)I (\d+)M{_TO}(\S+)\Z"),
    "fixer": re.compile(
        rf"\A(DONE|DISPUTED|BLOCKED) fixed (\d+) disputed (\d+) {_SHA}{_TO}(\S+)\Z"
    ),
    "implementer": re.compile(
        rf"\A(DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT) tests (\d+)/(\d+) {_SHA}{_TO}(\S+)\Z"
    ),
    "planner": re.compile(rf"\A(DONE|NEEDS_CONTEXT){_TO}(\S+)\Z"),
    "verifier": re.compile(rf"\A(PASS|FAIL){_TO}(\S+)\Z"),
}
_PATH_RE = re.compile(r"/dispatch/(?P<card>[^/]+)/(?P<stage>[^/]+)/(?P<name>[^/]+)\.md\Z")
_NAME_RE = re.compile(
    r"\A(?:r(?P<round>\d+)-(?P<slot>[A-Za-z0-9]+)|c(?P<chunk>\d+)|plan|verification|summary)\Z"
)


class ReplyError(ValueError):
    """An agent's final message that does not follow its role's reply grammar."""


@dataclass(frozen=True)
class Reply:
    role: str
    status: str
    line: str
    path: Path
    card: str
    stage: str
    name: str
    round: int | None = None
    slot: str | None = None
    chunk: int | None = None
    counts: dict[str, int] = field(default_factory=dict)
    sha: str | None = None


def agent_name(agent_type: object) -> str | None:
    """``overseer:overseer-reviewer`` (plugin agents carry the plugin prefix
    in hook payloads) or ``overseer-reviewer`` → ``overseer-reviewer``."""
    if not isinstance(agent_type, str) or not agent_type:
        return None
    return agent_type.split(":")[-1]


def role_of(agent_type: object) -> str | None:
    name = agent_name(agent_type)
    if not name or not name.startswith("overseer-"):
        return None
    role = name[len("overseer-"):]
    return role if role in ROLES else None


def is_hub_agent(agent_type: object) -> bool:
    """A hub dispatches rather than works (Phase 2's foreman); the guard
    holds it to the orchestrator's no-work rule."""
    return agent_name(agent_type) == "overseer-foreman"


def dispatch_dir(repo_root: Path, card_id: str, stage: str) -> Path:
    return state_root(repo_root) / "dispatch" / card_id / stage


def reply_words(text: str) -> int:
    return len(text.split())


def _name_fits(role: str, name: str, parts: re.Match[str]) -> bool:
    if role == "reviewer":
        return parts["round"] is not None and parts["slot"] != "fix"
    if role == "fixer":
        return parts["slot"] == "fix"
    if role == "implementer":
        return parts["chunk"] is not None
    return name == {"planner": "plan", "verifier": "verification"}[role]


def parse_reply(role: str, text: str) -> Reply:
    if role not in _GRAMMAR:
        raise ReplyError(f"no reply grammar for role {role!r}")
    line = text.strip()
    if "\n" in line:
        raise ReplyError("reply is more than one line")
    match = _GRAMMAR[role].match(line)
    if match is None:
        raise ReplyError(f"reply does not match the {role} grammar")
    groups = match.groups()
    where = _PATH_RE.search(groups[-1])
    if where is None:
        raise ReplyError("reply path is not a dispatch file")
    parts = _NAME_RE.match(where["name"])
    if parts is None or not _name_fits(role, where["name"], parts):
        raise ReplyError(f"file name {where['name']!r} does not fit a {role} reply")
    counts: dict[str, int] = {}
    sha: str | None = None
    if role == "reviewer":
        counts = {"C": int(groups[1]), "I": int(groups[2]), "M": int(groups[3])}
    elif role in ("fixer", "implementer"):
        keys = ("fixed", "disputed") if role == "fixer" else ("passed", "total")
        counts = {keys[0]: int(groups[1]), keys[1]: int(groups[2])}
        sha = None if groups[3] == "-" else groups[3]
    return Reply(
        role=role,
        status=groups[0],
        line=line,
        path=Path(groups[-1]),
        card=where["card"],
        stage=where["stage"],
        name=where["name"],
        round=int(parts["round"]) if parts["round"] else None,
        slot=parts["slot"],
        chunk=int(parts["chunk"]) if parts["chunk"] else None,
        counts=counts,
        sha=sha,
    )
