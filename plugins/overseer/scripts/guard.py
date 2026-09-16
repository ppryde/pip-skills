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

import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.dispatch import is_hub_agent, role_of
from scripts.models import Card, format_tokens

READ_LIMIT_DEFAULT = 400
_UNLIMITED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb")
# Edit/NotebookEdit are denied outright — there is no scratch-path exception
# for them (Edit needs an existing file; a scratch notebook isn't a real use
# case). Write gets the scratch-path exception below; it is not in this set.
_HARD_DENY_WRITE_TOOLS = {"Edit", "NotebookEdit"}
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
# Read-only inspection of the orchestrator's own allowed roots (state,
# plugins, config) — e.g. `grep -n foo <plugin>/scripts/cli.py` to check a
# verb's signature instead of guessing or re-reading SKILL.md.
_READ_ONLY_INSPECT = {"grep", "rg", "cat", "head", "tail", "less", "wc"}
# Scratch-space writers: a heredoc/echo/tee into /tmp, $TMPDIR or the
# overseer state root (never the repo worktree) — the orchestrator's way to
# stage a --file input without editing repo source.
_SCRATCH_WRITE_HEADS = {"cat", "echo", "printf", "tee"}
_REDIRECT_OPS = (">", ">>")
# Command substitution can smuggle a repo-source read (or worse) through an
# otherwise-allowed head (`echo $(cat secret) > /tmp/x`). Fail closed on any
# sign of it rather than trying to parse what it resolves to.
_SUBSTITUTION_RE = re.compile(r"\$\(|`")


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


def tmp_roots() -> list[Path]:
    """System scratch locations safe for a heredoc/Write during a live card
    — never the repo worktree. Computed fresh (not module-level) since
    ``$TMPDIR`` is per-process/session; macOS symlinks ``/tmp`` and the
    default tempdir to the same resolved place, so this naturally dedups."""
    seen: list[Path] = []
    for raw in (tempfile.gettempdir(), os.environ.get("TMPDIR", ""), "/tmp"):
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _within(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in roots)


def _word_within(word: str, cwd: object, roots: list[Path]) -> bool:
    path = Path(word).expanduser()
    if not path.is_absolute():
        if not isinstance(cwd, str):
            return False
        path = Path(cwd) / path
    return _within(path, roots)


def _is_path_like(word: str) -> bool:
    return not word.startswith("-") and ("/" in word or word.startswith("~"))


def _redirect_targets(words: list[str]) -> list[str]:
    return [words[i + 1] for i, w in enumerate(words) if w in _REDIRECT_OPS and i + 1 < len(words)]


def _read_only_allowed(words: list[str], cwd: object, roots: list[Path] | None) -> bool:
    """``grep``/``cat``/... of the orchestrator's own allowed roots (its
    state dir, the installed plugins, the config dir) — never a write, never
    a repo-source read."""
    if roots is None or any(w in _REDIRECT_OPS for w in words):
        return False
    paths = [w for w in words[1:] if _is_path_like(w)]
    return bool(paths) and all(_word_within(w, cwd, roots) for w in paths)


def _scratch_write_allowed(words: list[str], cwd: object, roots: list[Path] | None) -> bool:
    """A heredoc/echo/tee write, ONLY when every redirect target — and any
    other path-like word in the segment (e.g. a file it also reads) —
    resolves inside scratch space (``tmp_roots()`` + the state root) or,
    for a word that isn't a redirect target, the orchestrator's other
    allowed roots (reading an allowed file into a scratch copy)."""
    targets = _redirect_targets(words)
    if not targets:
        return False
    scratch = tmp_roots() + ([roots[0]] if roots else [])
    if not all(_word_within(t, cwd, scratch) for t in targets):
        return False
    readable = scratch + (roots or [])
    others = [w for w in words[1:] if _is_path_like(w) and w not in targets]
    return all(_word_within(w, cwd, readable) for w in others)


def bash_allowed(command: str, *, cwd: object = None, roots: list[Path] | None = None) -> bool:
    """Every segment of the command must be ledger/vigil CLI, git plumbing
    the orchestrator needs for branches/PRs, ``gh pr``, a bare ``cd``,
    read-only inspection of its own allowed roots, or a scratch-space write.
    ``$(...)``/backtick command substitution denies the whole command: it can
    smuggle a repo-source read through an otherwise-allowed head."""
    if _SUBSTITUTION_RE.search(command):
        return False
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
        if head in _READ_ONLY_INSPECT and _read_only_allowed(words, cwd, roots):
            continue
        if head in _SCRATCH_WRITE_HEADS and _scratch_write_allowed(words, cwd, roots):
            continue
        return False
    return True


def allowed_roots(state: Path, plugin_root: Path, config_dir: Path) -> list[Path]:
    """Where the orchestrator may still read: its ledger state (dispatch
    files included), the installed plugins (skills, references, templates),
    and the Claude config dir (memory, other skills)."""
    return [state.resolve(), plugin_root.parent.resolve(), config_dir.resolve()]


def _hub_denial(
    cards: list[Card], tool: str, tool_input: dict[str, object], cwd: object, roots: list[Path]
) -> str | None:
    """``cards`` is every live card this session orchestrates. Work/fork deny
    reasons name the first card (kept short); the tripwire check must look at
    all of them — a stacking session can be spending against any one."""
    card = cards[0]
    work = (
        f"{card.id} in flight: the orchestrator dispatches, it does not do the work — "
        f"dispatch an overseer-* agent with a dispatch-prep bundle instead. "
        f"(Escape hatch: {_ESCAPES}.)"
    )
    if tool == "Agent":
        breached = next((c for c in cards if c.tripwire_breached), None)
        if breached is not None:
            return (
                f"TRIPWIRE: {breached.id} has spent {format_tokens(breached.budget_actual)} "
                f"against an estimate of {format_tokens(breached.budget_estimate)} — stop the "
                "card and escalate to the user."
            )
    if tool in _HARD_DENY_WRITE_TOOLS or tool.startswith("mcp__"):
        return work
    if tool == "Write":
        raw = tool_input.get("file_path")
        if not isinstance(raw, str) or not raw:
            return work
        path = Path(raw).expanduser()
        if not path.is_absolute() and isinstance(cwd, str):
            path = Path(cwd) / path
        scratch = tmp_roots() + [roots[0]]  # the overseer state root, never the worktree
        return None if _within(path, scratch) else work
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
        return None if isinstance(command, str) and bash_allowed(command, cwd=cwd, roots=roots) else work
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
        if tool == "Agent" and tool_input.get("subagent_type") == "fork":
            return Verdict(
                f"{cards[0].id} in flight: forks inherit the full parent context — dispatch a "
                "fresh overseer-* agent with a bundle path instead."
            )
        is_hub = not payload.get("agent_id") or is_hub_agent(payload.get("agent_type"))
        if is_hub:
            reason = _hub_denial(cards, tool, tool_input, payload.get("cwd"), roots)
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
