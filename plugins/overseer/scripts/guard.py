"""PreToolUse guard and Read limit (WF-113 §5.1, §5.7).

The orchestrator is the most expensive party in an overseer run: every one of
its turns re-reads ~240k of context. This guard stops it doing work itself
(editing, reading source, running queries or tests) and stops anyone forking
(a fork inherits the whole parent context). Agents dispatched by the
orchestrator share its ``session_id`` but carry ``agent_id``, which is how
they are told apart (verified on Claude Code 2.1.273).

This is a cost guard, not a security boundary: command parsing is
best-effort and every doubt fails open.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from scripts.dispatch import is_hub_agent, role_of
from scripts.models import Card, format_tokens

READ_LIMIT_DEFAULT = 400
_UNLIMITED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb")
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
_PATH_TOOLS = {"Read", "Grep", "Glob"}
_OPERATORS = {"&&", "||", ";", "|", "&", ";;", "|&"}
_ASSIGNMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
_LEDGER_CLI = re.compile(
    r"(?:(?:\A|/)(?:overseer|vigil)/(?:[^/\s]+/)?|\$\{?CLAUDE_PLUGIN_ROOT\}?/)scripts/cli\.py\Z"
)
_GIT_SUBCOMMANDS = {
    "add", "branch", "commit", "diff", "fetch", "log", "merge-base", "pull", "push",
    "remote", "rev-parse", "show", "stash", "status", "symbolic-ref", "worktree",
}
_ESCAPES = '`release <card>`, `"guard": false` in .overseer/config.json, or OVERSEER_GUARD=off'


@dataclass(frozen=True)
class Verdict:
    deny_reason: str | None = None
    updated_input: dict[str, object] | None = None


def _segments(command: str) -> list[list[str]] | None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _OPERATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def bash_allowed(command: str) -> bool:
    """Every segment of the command must be ledger/vigil CLI, git plumbing
    the orchestrator needs for branches/PRs, ``gh pr``, or a bare ``cd``."""
    segments = _segments(command)
    if segments is None:
        return True
    for words in segments:
        while words and _ASSIGNMENT.match(words[0]):
            words = words[1:]
        if not words:
            continue
        head = Path(words[0]).name
        if head in {"cd", "pwd"} and len(words) <= 2:
            continue
        if head == "git":
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in {"-C", "-c"} else rest[1:]
            if rest and rest[0] in _GIT_SUBCOMMANDS:
                continue
            return False
        if head == "gh" and words[1:2] == ["pr"]:
            continue
        if head.startswith("python") and len(words) > 1 and _LEDGER_CLI.search(words[1]):
            continue
        return False
    return True


def allowed_roots(state: Path, plugin_root: Path, config_dir: Path) -> list[Path]:
    """Where the orchestrator may still read: its ledger state (dispatch
    files included), the installed plugins (skills, references, templates),
    and the Claude config dir (memory, other skills)."""
    return [state.resolve(), plugin_root.parent.resolve(), config_dir.resolve()]


def _within(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in roots)


def _hub_denial(
    card: Card, tool: str, tool_input: dict[str, object], cwd: object, roots: list[Path]
) -> str | None:
    work = (
        f"{card.id} in flight: the orchestrator dispatches, it does not do the work — "
        f"dispatch an overseer-* agent with a dispatch-prep bundle instead. "
        f"(Escape hatch: {_ESCAPES}.)"
    )
    if tool == "Agent" and card.tripwire_breached:
        return (
            f"TRIPWIRE: {card.id} has spent {format_tokens(card.budget_actual)} against an "
            f"estimate of {format_tokens(card.budget_estimate)} — stop the card and "
            "escalate to the user."
        )
    if tool in _WRITE_TOOLS or tool.startswith("mcp__"):
        return work
    if tool in _PATH_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("path")
        if not isinstance(raw, str) or not raw:
            return work
        path = Path(raw).expanduser()
        if not path.is_absolute() and isinstance(cwd, str):
            path = Path(cwd) / path
        return None if _within(path, roots) else work
    if tool == "Bash":
        command = tool_input.get("command")
        return None if isinstance(command, str) and bash_allowed(command) else work
    return None


def _limited_read(
    tool: str, tool_input: dict[str, object], payload: dict[str, object], limit: int
) -> dict[str, object] | None:
    if tool != "Read" or limit <= 0 or not payload.get("agent_id"):
        return None
    if role_of(payload.get("agent_type")) is None:
        return None
    if "limit" in tool_input or "offset" in tool_input:
        return None
    path = tool_input.get("file_path")
    if not isinstance(path, str) or path.lower().endswith(_UNLIMITED_SUFFIXES):
        return None
    return {**tool_input, "limit": limit}


def decide(
    payload: dict[str, object],
    cards: list[Card],
    roots: list[Path],
    *,
    read_limit: int = READ_LIMIT_DEFAULT,
) -> Verdict:
    """``cards`` = live cards whose orchestrator is this payload's session
    (empty when the guard is off). Deny beats the Read limit."""
    tool_raw = payload.get("tool_name")
    tool = tool_raw if isinstance(tool_raw, str) else ""
    input_raw = payload.get("tool_input")
    tool_input: dict[str, object] = input_raw if isinstance(input_raw, dict) else {}
    if cards:
        card = cards[0]
        if tool == "Agent" and tool_input.get("subagent_type") == "fork":
            return Verdict(
                f"{card.id} in flight: forks inherit the full parent context — dispatch a "
                "fresh overseer-* agent with a bundle path instead."
            )
        is_hub = not payload.get("agent_id") or is_hub_agent(payload.get("agent_type"))
        if is_hub:
            reason = _hub_denial(card, tool, tool_input, payload.get("cwd"), roots)
            if reason:
                return Verdict(reason)
    return Verdict(updated_input=_limited_read(tool, tool_input, payload, read_limit))


def hook_output(verdict: Verdict) -> dict[str, object] | None:
    """No ``permissionDecision`` with ``updatedInput``: verified on 2.1.273
    that the rewrite applies without one, so user permission rules still run."""
    if verdict.deny_reason:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": verdict.deny_reason,
        }}
    if verdict.updated_input is not None:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": verdict.updated_input,
        }}
    return None
