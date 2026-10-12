"""What happened to a tool call: classify an outcome, shape a command (stdlib only).

Subagent permission evidence (designs/subagent-permissions.md, ratified with
changes). Every tool_result in a transcript says whether its call ran, errored,
was denied (by the auto-mode classifier, a built-in safety check, the worktree
or sleep guard, a hook) or was held for a prompt. This module reads that text
ONCE to put the call in a fixed category and then drops it: the store keeps
categories, never error text, and never an argument.

Two rules make that safe:

- **Closed vocabularies.** ``classify`` returns an outcome from ``OUTCOMES``
  and a reason from a fixed list; ``shape`` prints a program only from an
  allowlist (anything else is ``(script)`` or ``(other)``) and a subcommand only
  from a per-program list. A mistyped token, a client-named script or a secret
  in the program position can therefore never reach a stored column.
- **Structured evidence first.** ``permissionDecision`` (Claude Code 2.1.295+)
  is preferred over phrase matching on the harness's text, which can drift: an
  unknown phrase lands in ``error:other`` and is counted, never dropped.

This module also runs ON A REMOTE BOX, concatenated between ``redact.py`` and
``remote_agent.py`` (see ``scripts.remote.bundle_source``), so it must stay
Python 3.8-compatible source (no walrus, no ``match``, no runtime-evaluated
``X | None``) and import nothing from the rest of chronicle. Its own
``from __future__`` line is dropped from the bundle.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Any

# ---------------------------------------------------------------- outcomes --
# (category, regex on the first 400 characters of the result text). First
# match wins. The ``denied:hook`` phrase has NO observed sample in 33k real
# results, so its pattern is a guess and its test fixture synthetic; the
# structured ``permissionDecision`` below is what actually identifies a hook.
_DENIAL_PATTERNS = (
    ("denied:classifier", re.compile(r"denied by the Claude Code auto mode classifier")),
    ("denied:classifier-unavailable", re.compile(
        r"auto mode classifier (is temporarily unavailable|gave no verdict)|"
        r"Auto mode could not evaluate|Classifier unavailable")),
    ("denied:safety-check", re.compile(r"denied by a built-in Claude Code safety check")),
    ("denied:worktree-guard", re.compile(r"is isolated in the worktree")),
    ("denied:sleep-guard", re.compile(r"Blocked: (standalone )?sleep")),
    ("denied:file-outside-root", re.compile(r"File access blocked: ")),
    ("denied:hook", re.compile(
        r"(PreToolUse|PermissionRequest):\S+ hook (error|blocked)|blocked by (a )?hook|"
        r"Hook (denied|blocked)")),
    ("denied:no-prompt-available", re.compile(
        r"(requires approval|permission prompt).*(non-interactive|cannot be shown)|"
        r"not allowed in this (context|agent)")),
    ("prompted:rejected", re.compile(
        r"doesn't want to proceed with this tool use|User rejected tool use")),
    ("prompted:interrupted", re.compile(r"Request interrupted by user")),
)
_ERROR_PATTERNS = (
    ("error:input-validation", re.compile(r"InputValidationError")),
    ("error:no-such-tool", re.compile(r"No such tool available")),
    ("error:fork-unavailable", re.compile(r"Fork is not available")),
    ("error:read-before-edit", re.compile(r"File has not been read yet|modified since read")),
    ("error:edit-no-match", re.compile(r"String to replace not found|Found \d+ matches")),
    ("error:not-found", re.compile(r"File does not exist|No such file|does not exist")),
    ("error:too-large", re.compile(r"exceeds maximum|characters across")),
    ("error:timeout", re.compile(r"timed out|Command timed out")),
    ("error:exit-code", re.compile(r"^(Error: )?Exit code \d+")),
)
_CLASSIFIER_REASON = re.compile(r"Reason: \[([^\]]{1,60})\]")
# The classifier's bracketed label is harness-authored; the six seen are listed.
# The label text itself is never stored: only the matching slug, else "other".
_CLASSIFIER_LABELS = {
    "modify-shared-resources": "modify-shared-resources",
    "irreversible-local-destruction": "irreversible-local-destruction",
    "auto-mode-bypass": "auto-mode-bypass",
    "create-unsafe-agents": "create-unsafe-agents",
    "instruction-poisoning": "instruction-poisoning",
}
_WORKTREE_SUBCAUSES = (
    ("wt:git-form-too-complex", re.compile(r"names git in a form too complex|feeds \w+ text naming git")),
    ("wt:too-complex", re.compile(r"too complex to verify")),
    ("wt:gh-query-text", re.compile(r"runs gh with the text")),
    ("wt:cd-shared-checkout", re.compile(r"changes directory to the shared checkout")),
    ("wt:runtime-computed", re.compile(r"computed at runtime")),
    ("wt:assigns-env", re.compile(r"assigns \w+ inside")),
)
_HEAD_CHARS = 400

OUTCOME_KINDS = (
    "ok",
    "error:input-validation", "error:no-such-tool", "error:fork-unavailable",
    "error:read-before-edit", "error:edit-no-match", "error:not-found", "error:too-large",
    "error:timeout", "error:exit-code", "error:other",
    "denied:classifier", "denied:classifier-unavailable", "denied:safety-check",
    "denied:worktree-guard", "denied:sleep-guard", "denied:file-outside-root", "denied:hook",
    "denied:config-rule", "denied:no-prompt-available",
    "prompted:approved", "prompted:rejected", "prompted:interrupted",
)
REASON_KINDS = tuple(sorted(
    set(_CLASSIFIER_LABELS.values())
    | {name for name, _ in _WORKTREE_SUBCAUSES}
    | {"wt:other", "unlabelled", "other"}))

# permissionDecision vocabularies: the values seen in real transcripts plus the
# allow-path sources named in the audit. Anything else is stored as "other".
_DECISIONS = ("accept", "reject")
_SOURCES = ("user_temporary", "user_permanent", "hook", "config", "classifier", "mode",
            "rule", "subcommandResults")
_REASON_TYPES = ("classifier", "safetyCheck", "hook", "rule", "mode", "subcommandResults")
_PROMPT_SOURCES = ("user_temporary", "user_permanent")


def result_head(payload: Any) -> str:
    """The first ``_HEAD_CHARS`` characters of a tool_result's TEXT: a string
    payload as is, a list of content blocks as their ``text`` joined. This is
    all ``classify`` ever looks at."""
    if isinstance(payload, list):
        payload = " ".join(
            b.get("text", "") for b in payload
            if isinstance(b, dict) and isinstance(b.get("text"), str))
    if not isinstance(payload, str):
        return ""
    return payload[:_HEAD_CHARS]


def clean_decision(raw: Any) -> dict[str, str] | None:
    """``permissionDecision`` reduced to ``{decision, source, reasonType}``
    with every value from a fixed vocabulary (``other`` for the unlisted), or
    None when ``raw`` is not a decision object."""
    if not isinstance(raw, dict):
        return None
    decision = raw.get("decision")
    source = raw.get("source")
    reason_type = raw.get("reasonType")
    out: dict[str, str] = {
        "decision": decision if decision in _DECISIONS else "other",
        "source": source if source in _SOURCES else "other",
    }
    if reason_type is not None:
        out["reasonType"] = reason_type if reason_type in _REASON_TYPES else "other"
    return out


def decision_fields(raw: Any) -> tuple[str | None, int]:
    """``(decision, prompted)`` for a ``permissionDecision``: the stored text
    ``<accept|reject>:<source>/<reasonType|->`` and 1 when a prompt was shown to
    a person (``user_*`` source), else 0. ``(None, 0)`` without a decision."""
    cleaned = clean_decision(raw)
    if cleaned is None:
        return None, 0
    text = f'{cleaned["decision"]}:{cleaned["source"]}/{cleaned.get("reasonType", "-")}'
    return text, 1 if cleaned["source"] in _PROMPT_SOURCES else 0


def _decision_outcome(raw: Any) -> str | None:
    cleaned = clean_decision(raw)
    if cleaned is None:
        return None
    if cleaned["source"] in _PROMPT_SOURCES:
        return "prompted:approved" if cleaned["decision"] == "accept" else "prompted:rejected"
    if cleaned["decision"] == "reject":
        return {"classifier": "denied:classifier", "safetyCheck": "denied:safety-check",
                "hook": "denied:hook"}.get(cleaned.get("reasonType", ""), "denied:config-rule")
    return None


def _classify_text(head: str) -> tuple[str, str | None]:
    text = re.sub(r"^<tool_use_error>", "", head.strip())
    # A failed command's own output can quote a harness phrase; a harness
    # denial never starts with the shell's exit-code header.
    if _ERROR_PATTERNS[-1][1].search(text):
        return _ERROR_PATTERNS[-1][0], None
    for category, pattern in _DENIAL_PATTERNS:
        if pattern.search(text):
            reason = None
            if category == "denied:classifier":
                found = _CLASSIFIER_REASON.search(text)
                if not found:
                    reason = "unlabelled"
                else:
                    slug = re.sub(r"[^a-z0-9]+", "-", found.group(1).lower()).strip("-")
                    reason = _CLASSIFIER_LABELS.get(slug, "other")
            elif category == "denied:worktree-guard":
                reason = next((name for name, rx in _WORKTREE_SUBCAUSES if rx.search(text)), "wt:other")
            return category, reason
    for category, pattern in _ERROR_PATTERNS:
        if pattern.search(text):
            return category, None
    return "error:other", None


def classify(result: Any, is_error: bool,
             permission_decision: Any = None) -> tuple[str, str | None]:
    """``(outcome, reason)`` for one tool_result. ``result`` is the block's
    ``content`` (text or content blocks). ``outcome`` is always in
    ``OUTCOME_KINDS`` and ``reason`` None or in ``REASON_KINDS``; the result
    text itself is read here and nowhere kept.

    A structured denial or rejection in ``permission_decision`` wins over a
    generic ``error:*`` from the text (the harness said so outright); an
    APPROVED prompt never turns an error into a success, and is the outcome of
    a call that then ran fine."""
    decided = _decision_outcome(permission_decision)
    if not is_error:
        return (decided if decided == "prompted:approved" else "ok"), None
    category, reason = _classify_text(result_head(result))
    if decided and decided != "prompted:approved" and category.startswith("error:"):
        return decided, reason
    return category, reason


def valid_outcome(outcome: Any, reason: Any = None) -> bool:
    """Whether an ``_outcome``/``_reason`` pair read off a redacted transcript
    is inside the closed vocabularies (a hostile mirror cannot widen them)."""
    return outcome in OUTCOME_KINDS and (reason is None or reason in REASON_KINDS)


# ------------------------------------------------------------------- shape --
_WRAPPERS = ("sudo", "env", "time", "nice", "timeout", "command", "exec", "xargs")
_NUMERIC_WRAPPERS = ("timeout", "nice")
_NUMERIC_ARG = re.compile(r"^[0-9]+(\.[0-9]+)?[smhd]?$")

# Subcommands printed after a program, per program. A word not listed prints
# nothing (the program alone), so the vocabulary is closed at both positions.
_SUBCOMMANDS = {
    "git": ("add", "am", "apply", "bisect", "blame", "branch", "checkout", "cherry-pick", "clean",
            "clone", "commit", "config", "diff", "fetch", "grep", "init", "log", "ls-files",
            "ls-tree", "merge", "mv", "pull", "push", "rebase", "remote", "reset", "restore",
            "rev-list", "rev-parse", "revert", "rm", "show", "stash", "status", "switch", "tag",
            "worktree"),
    "gh": ("api", "auth", "issue", "pr", "release", "repo", "run", "workflow"),
    "poetry": ("add", "build", "check", "install", "lock", "remove", "run", "show", "update"),
    "uv": ("add", "pip", "run", "sync", "tool", "venv"),
    "npm": ("ci", "exec", "install", "run", "test", "view"),
    "npx": (), "pnpm": ("install", "run", "test"), "yarn": ("install", "run", "test"),
    "bun": ("install", "run", "test", "x"),
    "docker": ("build", "compose", "exec", "images", "logs", "ps", "pull", "run", "volume"),
    "claude": ("agents", "config", "mcp", "plugin"),
    "pip": ("install", "list", "show", "uninstall"), "pip3": ("install", "list", "show", "uninstall"),
    "cargo": ("build", "check", "clippy", "fmt", "run", "test"),
    "go": ("build", "fmt", "mod", "run", "test", "vet"),
    "brew": ("install", "list", "info", "update"),
    "sqlite3": (), "make": (),
}
# A second word is kept only for these (e.g. `gh pr view`, `poetry run pytest`).
_SECOND_WORD = {
    "gh": ("checks", "close", "comment", "create", "diff", "edit", "list", "merge", "review",
           "status", "view"),
    "poetry": ("mypy", "pytest", "python", "ruff"),
    "uv": ("install", "run"),
}
# Global flags whose next token is a value, not the subcommand.
_VALUE_FLAGS = {"git": ("-C", "-c", "--git-dir", "--work-tree", "--namespace")}
_PROGRAMS = frozenset((
    "ls", "cat", "head", "tail", "grep", "sed", "awk", "find", "diff", "mkdir", "rm", "cp", "mv",
    "echo", "printf", "pwd", "which", "curl", "tar", "python", "python3", "pytest", "ruff",
    "mypy", "sqlite3", "bash", "sh", "nohup", "sleep",
)) | frozenset(_SUBCOMMANDS)
_PYTHON = re.compile(r"^python[0-9.]*$")
_PY_MODULES = ("pytest", "ruff", "mypy", "pip", "venv", "json.tool", "unittest", "black",
               "build", "http.server", "compileall")
_COMPOUND = re.compile(r"&&|\|\||;|\||\$\(|`|<<")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PREAMBLE = re.compile(r"^(cd|pushd|set|source|\.)(\s|$)")
_LOOP = re.compile(r"^(for|while|until|if|do|done|then|fi|case)\b")


def _program_name(token: str) -> str:
    """The printable program for ``token``: its basename when that is on the
    allowlist (``.venv/bin/python`` -> ``python``), ``(script)`` for a script
    or any other path-like token, else ``(other)``. A token never prints as
    itself unless it IS an allowlisted name."""
    base = os.path.basename(token)
    if base in _PROGRAMS or _PYTHON.match(base):
        return base
    if "/" in token or base.endswith((".sh", ".py", ".bash", ".zsh")):
        return "(script)"
    return "(other)"


def bash_shape(command: str) -> str:
    """``git status``, ``python3 -m pytest``, ``poetry run pytest``, ... plus
    `` +compound``. Arguments, paths and values are never kept, and the
    program position is a closed set (see ``_program_name``)."""
    compound = bool(_COMPOUND.search(command))
    segments = [s.strip() for s in re.split(r"&&|\|\||;|\||\n", command)]
    segments = [s for s in segments if s and not s.startswith("#") and not _PREAMBLE.match(s)]
    tokens: list[str] = []
    for first in segments:
        if _LOOP.match(first):
            return "(shell-block)" + (" +compound" if compound else "")
        try:
            tokens = shlex.split(first, comments=True)
        except ValueError:
            tokens = first.split()
        while tokens and _ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
        if tokens and tokens[0] in ("export", "local", "declare") and len(tokens) == 1:
            tokens = []
        if tokens:
            break
    while tokens and tokens[0] in _WRAPPERS:
        wrapper = tokens[0]
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            flag = tokens[0]
            tokens = tokens[1:]
            if wrapper == "timeout" and flag in ("-s", "-k", "--signal", "--kill-after") and tokens:
                tokens = tokens[1:]
        if wrapper in _NUMERIC_WRAPPERS:
            while tokens and _NUMERIC_ARG.match(tokens[0]):
                tokens = tokens[1:]
        tokens = [t for t in tokens if not _ASSIGNMENT.match(t)] if wrapper == "env" else tokens
    if not tokens:
        return "(empty)"
    program = _program_name(tokens[0])
    shape = program
    rest: list[str] = []
    skip = False
    for token in tokens[1:]:
        if skip:
            skip = False
        elif token.startswith("-"):
            skip = token in _VALUE_FLAGS.get(program, ())
        else:
            rest.append(token)
    if program in _SUBCOMMANDS and rest and rest[0] in _SUBCOMMANDS[program]:
        shape += " " + rest[0]
        if len(rest) > 1 and rest[1] in _SECOND_WORD.get(program, ()):
            shape += " " + rest[1]
    elif _PYTHON.match(program) and "-m" in tokens:
        index = tokens.index("-m")
        module = tokens[index + 1] if index + 1 < len(tokens) else ""
        shape += " -m " + (module if module in _PY_MODULES else "(other)")
    elif _PYTHON.match(program) and rest:
        shape += " <script>" if rest[0].endswith(".py") else " <inline>"
    return shape + (" +compound" if compound else "")


_SHAPE_OK = re.compile(r"^[A-Za-z0-9_.<>()+ -]{1,60}$")


def tool_shape(name: Any, tool_input: Any) -> str | None:
    """The stored shape of one tool call, or None when there is none to give.
    Bash: ``bash_shape`` of the command (None without a string command, e.g. a
    redacted input). MCP tools collapse to ``mcp__<server>__*``; every other
    tool is its own name (qualifiers live in ``tool_calls.qualifier``)."""
    if not isinstance(name, str) or not name:
        return None
    if name == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if isinstance(command, str) and command.strip():
            return bash_shape(command)
        stood_in = tool_input.get("_shape") if isinstance(tool_input, dict) else None
        return stood_in if isinstance(stood_in, str) and _SHAPE_OK.match(stood_in) else None
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"mcp__{parts[1][:40]}__*" if len(parts) > 2 and parts[1] else "mcp__*"
    return name[:40]


# -------------------------------------------------------------- agent types --
BUILTIN_AGENT_TYPES = ("general-purpose", "Explore", "Plan", "fork", "claude-code-guide", "?")
AD_HOC = "(ad-hoc)"
_PLUGIN_AGENT = re.compile(r"^[A-Za-z0-9_.-]{1,40}:[A-Za-z0-9_.-]{1,60}$")


def fold_agent_type(value: Any) -> str | None:
    """An ``agentType`` as it may be stored below ``titles``: a built-in or a
    ``<plugin>:<name>`` stays; any other name (a model- or user-written label
    such as ``wf-087-gate1b``) is ``(ad-hoc)``. None for no value."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value in BUILTIN_AGENT_TYPES or _PLUGIN_AGENT.match(value):
        return value
    return AD_HOC
