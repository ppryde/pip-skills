"""PreToolUse guard and Read limit (WF-113 §5.1, §5.7).

The orchestrator is the most expensive party in an overseer run: every one of
its turns re-reads ~240k of context. This guard stops it doing work itself
(editing, reading source, running queries or tests) and stops anyone forking
(a fork inherits the whole parent context). Agents dispatched by the
orchestrator share its ``session_id`` but carry ``agent_id``, which is how
they are told apart (verified on Claude Code 2.1.273).

This is a cost guard, not a security boundary. Command parsing is done by
``scripts/shellscan.py`` and FAILS CLOSED: a command whose quote or heredoc
state the scanner cannot model exactly is denied (a bash syntax error costs
the orchestrator nothing). The Read limit and the hook as a whole still fail
open on any internal error.

The module is stdlib-only (no PyYAML, no card model): ``hookfast.py`` imports
it on every guarded tool call.
"""
from __future__ import annotations

import functools
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts import shellscan
from scripts.dispatch import is_hub_agent, role_of
from scripts.tokens import format_tokens

READ_LIMIT_DEFAULT = 400
_UNLIMITED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb")
# Edit/NotebookEdit are denied outright — there is no scratch-path exception
# for them (Edit needs an existing file; a scratch notebook isn't a real use
# case). Write gets the scratch-path exception below; it is not in this set.
_HARD_DENY_WRITE_TOOLS = {"Edit", "MultiEdit", "NotebookEdit"}
_PATH_TOOLS = {"Read", "Grep", "Glob"}
_ASSIGNMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
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
# Interpreter flags that take no argument and do not change which file runs.
_PY_FLAGS = {"-I", "-u", "-B", "-E", "-s", "-S", "-O", "-OO", "-q"}
_CLI_MANIFEST_NAMES = {"overseer", "vigil"}
_MSG_SUBSTITUTION = (
    "GUARD: live command substitution ($(...), backticks, <(...)) — put the text in a file "
    "and pass --text-file / --brief-file, pipe it with --text - / --brief - and a quoted "
    "heredoc, or single-quote it"
)
_MSG_GLOBS = "GUARD: no globs in a read-only or scratch-write command — name the file"
_MSG_VARS = (
    "GUARD: no $variables in a path (a redirect target, CLI script or read-only/scratch path) — "
    "write the literal path"
)
# Assigning any of these changes what the guard's own expansion means.
_TAINTING_VARS = {"CLAUDE_PLUGIN_ROOT", "PATH", "HOME", "PYTHONPATH", "TMPDIR"}


@dataclass(frozen=True)
class GuardCard:
    """The four card fields the guard reads — what ``hookfast`` selects from
    ``board.db`` without loading a full ``Card``. ``Card`` duck-types this."""

    id: str
    worktree: str | None
    budget_estimate: int | None
    budget_actual: int

    @property
    def tripwire_breached(self) -> bool:
        # Same rule as ``Card.tripwire_breached`` (parity-tested).
        if self.budget_estimate is None:
            return False
        return self.budget_actual >= 2 * self.budget_estimate


@dataclass(frozen=True)
class Verdict:
    deny_reason: str | None = None
    updated_input: dict[str, object] | None = None


def _own_cli() -> Path:
    """The real path of THIS plugin's ``scripts/cli.py``."""
    return _own_cli_cached()


@functools.lru_cache(maxsize=1)
def _own_cli_cached() -> Path:
    return Path(os.path.realpath(Path(__file__).resolve().parent / "cli.py"))


def _config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def _plugin_dirs() -> list[Path]:
    """Where an overseer/vigil plugin root may live (verdict change 7).

    ``own.parent.parent.parent`` is the *versions folder*
    (``.../cache/pip-skills/overseer``) in a marketplace install — so it
    covers other installed versions of overseer — and ``repos/pip-skills/
    plugins`` in a ``--plugin-dir`` dev install, where it covers the sibling
    ``vigil``. A sibling plugin in the marketplace cache
    (``.../cache/pip-skills/vigil/0.2.0``) is covered only by
    ``<config dir>/plugins``.
    """
    own = _own_cli()
    return [
        Path(os.path.realpath(own.parent.parent.parent)),
        Path(os.path.realpath(_config_dir() / "plugins")),
    ]


@functools.lru_cache(maxsize=64)
def _manifest_name(root: Path) -> str | None:
    """``name`` from ``<root>/.claude-plugin/plugin.json`` of THIS root only
    (never walks up). Missing or unparseable -> None, which denies."""
    try:
        data = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


def is_cli(real: Path) -> bool:
    """Is ``real`` (an already-resolved path) an overseer/vigil ledger CLI?
    Real-path identity only — no lexical normalisation anywhere: a symlink
    trick resolves to the real file, which must be this plugin's own CLI or a
    manifest-named overseer/vigil ``scripts/cli.py`` inside an installed
    plugin tree. A dangling symlink still "resolves", hence ``is_file``."""
    if not real.is_file():
        return False
    if real == _own_cli():
        return True
    if real.name != "cli.py" or real.parent.name != "scripts":
        return False
    root = real.parent.parent
    if not any(root.is_relative_to(d) for d in _plugin_dirs()):
        return False
    return _manifest_name(root) in _CLI_MANIFEST_NAMES


def _manifest_version(root: Path) -> tuple[int, ...]:
    try:
        data = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
        return tuple(int(p) for p in str(data.get("version", "0")).split("."))
    except (OSError, ValueError, AttributeError):
        return (0,)


def find_sibling_cli(name: str) -> Path | None:
    """The newest installed ``scripts/cli.py`` of the sibling plugin ``name``
    (``vigil``), found under the same ``_plugin_dirs()`` the guard trusts and
    verified by manifest name (verdict change 8). Repo layout:
    ``<plugins>/vigil``; marketplace cache: ``.../cache/<market>/vigil/<ver>``.
    Newest manifest version wins, so a session that outlives an update still
    finds one."""
    found: list[tuple[tuple[int, ...], Path]] = []
    for base in _plugin_dirs():
        patterns = (f"{name}", f"{name}/*", f"cache/*/{name}/*")
        for pattern in patterns:
            for root in base.glob(pattern):
                cli = Path(os.path.realpath(root / "scripts" / "cli.py"))
                if _manifest_name(root.resolve()) == name and cli.is_file():
                    found.append((_manifest_version(root), cli))
    if not found:
        return None
    return max(found, key=lambda item: item[0])[1]


def _expand_cli_word(word: str) -> str:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(_own_cli().parent.parent)
    word = word.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root).replace(
        "$CLAUDE_PLUGIN_ROOT", plugin_root
    )
    return os.path.expanduser(word) if word.startswith("~") else word


def _cli_denial(words: list[str], cwd: object) -> str | None:
    """None = ``words`` is a ``python[3] <ledger cli> ...`` call. Otherwise
    the reason it is not (the deny message names the resolved path)."""
    i = 1
    while i < len(words) and words[i] in _PY_FLAGS:
        i += 1
    if i >= len(words) or words[i].startswith("-"):
        return "GUARD: not a ledger CLI (python -c / -m / no script)"
    script = _expand_cli_word(words[i])
    if "$" in script or "`" in script:
        return f"GUARD: not a ledger CLI (cannot resolve {script!r})"
    if not os.path.isabs(script):
        if not isinstance(cwd, str) or not cwd:
            return f"GUARD: not a ledger CLI (relative path {script!r} and no working directory)"
        script = os.path.join(cwd, script)
    real = Path(os.path.realpath(script))
    if not real.exists():
        return f"GUARD: cli not found at {real}"
    if is_cli(real):
        return None
    return (
        f"GUARD: not a ledger CLI ({real} is not an installed overseer/vigil scripts/cli.py "
        f"under {', '.join(str(d) for d in _plugin_dirs())})"
    )


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


def protected_roots(
    repo_root: Path | None, cards: Sequence[GuardCard], extra: Sequence[Path] = ()
) -> list[Path]:
    """Real source, never scratch space regardless of where it happens to
    live: the orchestrator's own repo root (and ``extra`` — the canonical root
    the marker names, when the payload ``cwd`` is somewhere else), and every
    live card's worktree. Needed because scratch space (``tmp_roots()``) is a
    SYSTEM location, not a project one — a repo or worktree checked out under
    ``/tmp``/``$TMPDIR`` (a benchmark fixture did exactly this) would
    otherwise fall inside it."""
    protected: list[Path] = []
    for root in (repo_root, *extra):
        if root is None:
            continue
        try:
            protected.append(Path(root).resolve())
        except OSError:
            pass
    for card in cards:
        if not card.worktree:
            continue
        try:
            protected.append(Path(card.worktree).resolve())
        except OSError:
            continue
    return protected


def _word_is_scratch(word: str, cwd: object, scratch: list[Path], protected: list[Path]) -> bool:
    """Inside scratch space AND not inside the repo root or a card worktree
    — the repo-under-/tmp exclusion, applied per word."""
    path = Path(word).expanduser()
    if not path.is_absolute():
        if not isinstance(cwd, str):
            return False
        path = Path(cwd) / path
    return _within(path, scratch) and not _within(path, protected)


def _is_path_like(word: str) -> bool:
    return not word.startswith("-") and ("/" in word or word.startswith("~"))


def _file_writes(command: shellscan.Command) -> list[shellscan.Redirect]:
    """Redirects that open a file for writing, other than ``/dev/null``."""
    return [r for r in command.redirects if r.writes and r.target != "/dev/null"]


def _read_only_allowed(
    command: shellscan.Command,
    words: list[str],
    cwd: object,
    roots: list[Path] | None,
    protected: list[Path],
) -> bool:
    """``grep``/``cat``/... of the orchestrator's own allowed roots (its
    state dir, the installed plugins, the config dir) — never a write, never
    a repo-source read. ``protected`` excludes the repo/worktree in case one
    of them happens to sit under an allowed root (shouldn't normally, but the
    scratch-write exclusion below needs the same check, so it's shared)."""
    if roots is None or _file_writes(command):
        return False
    paths = [w for w in words[1:] if _is_path_like(w)]
    return bool(paths) and all(
        _word_within(w, cwd, roots) and not _word_within(w, cwd, protected) for w in paths
    )


def _scratch_write_allowed(
    command: shellscan.Command,
    words: list[str],
    cwd: object,
    roots: list[Path] | None,
    protected: list[Path],
) -> bool:
    """A heredoc/echo/tee write, ONLY when every redirect target — and any
    other path-like word in the segment (e.g. a file it also reads) —
    resolves inside scratch space (``tmp_roots()`` + the state root) or,
    for a word that isn't a redirect target, the orchestrator's other
    allowed roots (reading an allowed file into a scratch copy) — and NONE of
    them fall inside the repo root or a live card's worktree, even if that
    worktree happens to live under scratch space (e.g. checked out under
    ``/tmp``)."""
    targets = [r.target for r in _file_writes(command)]
    if not targets:
        return False
    scratch = tmp_roots() + ([roots[0]] if roots else [])
    if not all(_word_is_scratch(t, cwd, scratch, protected) for t in targets):
        return False
    readable = scratch + (roots or [])
    others = [w for w in words[1:] if _is_path_like(w) and w not in targets]
    return all(
        _word_within(w, cwd, readable) and not _word_within(w, cwd, protected) for w in others
    )


def _redirect_denial(
    command: shellscan.Command, cwd: object, roots: list[Path] | None, protected: list[Path]
) -> str | None:
    """Every redirect on EVERY command (a ledger-CLI or version-control
    segment included, verdict change 3): an output target must be scratch or
    ``/dev/null``; an input target must be readable scratch or an allowed
    root, never repo source. fd duplications (``2>&1``, ``>&2``) involve no
    file."""
    scratch = tmp_roots() + ([roots[0]] if roots else [])
    readable = scratch + (roots or [])
    for r in command.redirects:
        if r.fd_dup or r.target == "/dev/null":
            continue
        if r.glob:
            return _MSG_GLOBS
        if "$" in r.target:
            return _MSG_VARS
        if r.writes:
            if not _word_is_scratch(r.target, cwd, scratch, protected):
                return f"GUARD: redirect to {r.target} — output may only go to scratch or /dev/null"
        elif not (
            _word_within(r.target, cwd, readable) and not _word_within(r.target, cwd, protected)
        ):
            return (
                f"GUARD: redirect from {r.target} — input may only come from scratch "
                "or an allowed root"
            )
    return None


def bash_check(
    command: str,
    *,
    cwd: object = None,
    roots: list[Path] | None = None,
    protected: list[Path] | None = None,
) -> tuple[bool, str | None]:
    """``(allowed, reason)``. ``reason`` is a specific ``GUARD: ...`` line, or
    None for the generic denial. Every segment of the command must be
    ledger/vigil CLI (by real path), plumbing the orchestrator needs for
    branches/PRs, ``gh pr``, a bare ``cd``, read-only inspection of its own
    allowed roots, or a scratch-space write. Live command substitution
    (``$(...)``, backticks, ``<(...)``, ``>(...)``) and anything the scanner
    cannot model deny the whole command — it can smuggle a repo-source read
    through an otherwise-allowed head."""
    protected = protected or []
    scanned = shellscan.scan(command)
    if scanned.live:
        return False, _MSG_SUBSTITUTION
    if scanned.error:
        return False, f"GUARD: cannot parse command ({scanned.error})"
    cur_cwd = cwd
    prev_sep = ";"  # what preceded the current command ("start" behaves like ";")
    for cmd in scanned.commands:
        before, prev_sep = prev_sep, cmd.sep
        denial = _redirect_denial(cmd, cur_cwd, roots, protected)
        if denial:
            return False, denial
        words, globs = list(cmd.words), list(cmd.globs)
        while words and _ASSIGNMENT.match(words[0]):
            name = words[0].split("=", 1)[0]
            if name in _TAINTING_VARS:
                return False, f"GUARD: assignment to {name} is not allowed"
            words, globs = words[1:], globs[1:]
        if not words:
            continue
        head = Path(words[0]).name
        if head in {"cd", "pwd"} and len(words) <= 2:
            if head == "cd":
                # A cd only takes effect in the shell when it runs unconditionally
                # and in the main shell: preceded by nothing/`;`/newline AND
                # followed by `;`/newline/`&&`/nothing. Anything else (`A || cd`,
                # `A && cd`, `A | cd`, `cd &`) may or may not run, so the cwd is
                # unknowable and relative CLI paths are denied.
                trusted = before in (";", "\n") and cmd.sep in (";", "\n", "&&", "")
                cur_cwd = _cd_target(words, globs, cur_cwd) if trusted else None
            continue
        if head == "git":
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in {"-C", "-c"} else rest[1:]
            if rest and rest[0] in _GIT_SUBCOMMANDS:
                continue
            return False, None
        if head == "gh" and words[1:2] == ["pr"]:
            continue
        if head.startswith("python") and len(words) > 1:
            why = _cli_denial(words, cur_cwd)
            if why is None:
                continue
            return False, why
        if head in _READ_ONLY_INSPECT or head in _SCRATCH_WRITE_HEADS:
            if any(globs):
                return False, _MSG_GLOBS
            if any("$" in w and _is_path_like(w) for w in words[1:]):
                return False, _MSG_VARS
            if head in _READ_ONLY_INSPECT and _read_only_allowed(
                cmd, words, cur_cwd, roots, protected
            ):
                continue
            if head in _SCRATCH_WRITE_HEADS and _scratch_write_allowed(
                cmd, words, cur_cwd, roots, protected
            ):
                continue
        return False, None
    return True, None


def _cd_target(words: list[str], globs: list[bool], cwd: object) -> str | None:
    """The working directory after ``cd <dir>``; None when it cannot be known
    (``cd``, ``cd -``, a variable or glob, or a relative dir with no cwd)."""
    if len(words) != 2:
        return None
    target = words[1]
    if target.startswith("-") or "$" in target or globs[1]:
        return None
    path = Path(target).expanduser()
    if not path.is_absolute():
        if not isinstance(cwd, str):
            return None
        path = Path(cwd) / path
    return str(path) if path.is_dir() else None  # a failed cd never moves the shell


def bash_allowed(
    command: str,
    *,
    cwd: object = None,
    roots: list[Path] | None = None,
    protected: list[Path] | None = None,
) -> bool:
    return bash_check(command, cwd=cwd, roots=roots, protected=protected)[0]


def allowed_roots(state: Path, plugin_root: Path, config_dir: Path) -> list[Path]:
    """Where the orchestrator may still read: its ledger state (dispatch
    files included), the installed plugins (skills, references, templates),
    and the Claude config dir (memory, other skills)."""
    return [state.resolve(), plugin_root.parent.resolve(), config_dir.resolve()]


def _hub_denial(
    cards: Sequence[GuardCard],
    tool: str,
    tool_input: dict[str, object],
    cwd: object,
    roots: list[Path],
    protected: list[Path],
) -> str | None:
    """``cards`` is every live card this session orchestrates. Work/fork deny
    reasons name the first card (kept short); the tripwire check must look at
    all of them — a stacking session can be spending against any one.
    ``protected`` (repo root + every live worktree) excludes real source from
    the scratch-space exceptions below, even when a worktree happens to live
    under ``/tmp``/``$TMPDIR``."""
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
        scratch = tmp_roots() + [roots[0]]  # the overseer state root, never the worktree
        return None if _word_is_scratch(raw, cwd, scratch, protected) else work
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
        if not isinstance(command, str):
            return work
        allowed, why = bash_check(command, cwd=cwd, roots=roots, protected=protected)
        if allowed:
            return None
        return work if why is None else f"{card.id} in flight: {why}. (Escape hatch: {_ESCAPES}.)"
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
    cards: Sequence[GuardCard],
    roots: list[Path],
    *,
    read_limit: int = READ_LIMIT_DEFAULT,
    repo_root: Path | None = None,
    extra_protected: Sequence[Path] = (),
) -> Verdict:
    """``cards`` = live cards whose orchestrator is this payload's session
    (empty when the guard is off). Deny beats the Read limit. ``repo_root``
    (with every live card's worktree) is excluded from the scratch-space
    write exceptions — see ``protected_roots`` (``extra_protected`` is the
    marker's canonical root, protected alongside the payload ``cwd``)."""
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
            protected = protected_roots(repo_root, cards, extra_protected)
            reason = _hub_denial(cards, tool, tool_input, payload.get("cwd"), roots, protected)
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
