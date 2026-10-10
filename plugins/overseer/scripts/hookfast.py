"""Cheap PreToolUse entry point (WF-265 PR A, OL-7).

``cli.py pretool-hook`` imports the 94 KB CLI, PyYAML and every module, opens
the board read-write (schema pass, pragmas, ``git`` subprocesses) and only then
asks one question. This module answers the same question with the standard
library alone: ``json``, ``sqlite3``, ``os``, ``pathlib`` plus ``guard`` and
``shellscan``/``marker`` (themselves stdlib). No PyYAML, no ``cli.py``, no
``git``, no schema pass.

It also hosts the git-push probe used by ``prepush-snapshot.sh`` so that hook
needs one interpreter start (not up to three) to decide whether to act.

Contract: print a JSON decision, or nothing. An internal error exits 0 with no
output (fail open) EXCEPT for a Bash call from an orchestrating session, which
is denied with a reason (fail closed); an import failure at load time is
caught the same way (see ``main``).
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):  # direct script invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts import guard, marker, shellscan
    _IMPORT_ERROR: BaseException | None = None
except Exception as _exc:  # noqa: BLE001 -- a half-upgraded tree: main() turns this into a deny
    guard = marker = shellscan = None  # type: ignore[assignment]
    _IMPORT_ERROR = _exc

GUARD_ENV = "OVERSEER_GUARD"
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def load_config(repo: Path | None) -> dict[str, object]:
    """``<repo>/.overseer/config.json`` then ``config.local.json`` (local
    wins) — the same precedence as ``config.load_config`` without its git
    lookup: the caller already holds the canonical root."""
    return marker.load_repo_config(repo)


def evaluate(
    payload: dict[str, object],
    boards: marker.Board | Sequence[marker.Board] | None,
    *,
    config_repo: Path | None = None,
) -> dict[str, object] | None:
    """The hook decision for ``payload`` as hook JSON, or None.

    ``boards`` are the boards the session orchestrates on (from its marker, or
    resolved by the CLI wrapper); none means "no known orchestration" -- only
    the Read limit can apply. ``config_repo`` overrides where the guard config
    is read from (defaults to the first board's repo, else the payload ``cwd``).
    """
    board_list: list[marker.Board] = (
        [] if boards is None else [boards] if isinstance(boards, marker.Board) else list(boards)
    )
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    cwd_path = Path(cwd) if isinstance(cwd, str) and cwd else None
    cfg = load_config(config_repo or (board_list[0].repo if board_list else cwd_path))
    guard_on = (
        os.environ.get(GUARD_ENV, "").lower() != "off" and cfg.get("guard", True) is not False
    )
    cards: list[guard.GuardCard] = []
    if board_list and guard_on and isinstance(session_id, str) and session_id:
        for board in board_list:
            found = marker.live_cards(board.db, session_id)
            if found is None:
                continue
            cards.extend(found)
            if not found:  # nothing live on this board: drop it from the marker
                try:
                    marker.remove_marker(session_id, board.db)
                except OSError:
                    pass
    state = board_list[0].state if board_list else marker.config_dir()
    roots = guard.allowed_roots(state, _PLUGIN_ROOT, marker.config_dir())
    limit = cfg.get("read_limit", guard.READ_LIMIT_DEFAULT)
    # Protected roots = the payload cwd (what the orchestrator is standing in)
    # AND every marker board's canonical root (verdict change 11), plus every
    # live card's worktree (added by ``guard.decide``).
    verdict = guard.decide(
        payload, cards, roots,
        read_limit=limit if isinstance(limit, int) and not isinstance(limit, bool)
        else guard.READ_LIMIT_DEFAULT,
        repo_root=cwd_path,
        extra_protected=[b.repo for b in board_list],
    )
    return guard.hook_output(verdict)


def run(raw: str) -> dict[str, object] | None:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id")
    sid = session_id if isinstance(session_id, str) and session_id else None
    directory = marker.marker_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)  # next call takes the shell fast path
    except OSError:
        pass
    boards = marker.read_boards(sid) if sid else []
    writable = os.access(directory, os.W_OK)
    if sid and not boards and (not writable or not marker.is_checked(sid)):
        # First call of THIS session (upgrade window: it may already be
        # orchestrating, with no marker yet) or an unwritable marker dir: the
        # shell had no marker to trust, so ask the boards themselves
        # (read-only, no git), leave a marker behind if there is something to
        # guard, and remember that this session has been looked up.
        cwd = payload.get("cwd")
        boards, complete = marker.lookup_boards(
            sid, Path(cwd) if isinstance(cwd, str) and cwd else None)
        for board in boards:
            try:
                marker.write_marker(sid, board)
            except OSError as exc:
                print(f"overseer: cannot write the guard marker in {directory}: {exc}; "
                      "the full guard runs on every tool call until it is writable",
                      file=sys.stderr)
        if complete:  # a locked/unreadable board means "look again next call"
            try:
                marker.mark_checked(sid)
            except OSError:
                pass
        try:
            marker.sweep_if_due()
        except OSError:
            pass
    return evaluate(payload, boards)


def is_git_push(command: str) -> bool:
    """Does any simple command in ``command`` run ``git push``? Uses the
    shell scanner, so a ``push`` inside a quoted argument or a heredoc body
    never matches, an unquoted newline separates commands, and a quoted
    ``git -C "/my repo" push`` does match. A command the scanner cannot model
    does not fire (as before)."""
    scanned = shellscan.scan(command)
    if scanned.error:
        return False
    with_arg = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                "--super-prefix"}
    for cmd in scanned.commands:
        words = list(cmd.words)
        while words and "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]  # leading VAR=value assignments
        if not words or words[0] != "git":
            continue
        i = 1
        while i < len(words):
            if words[i] in with_arg:
                i += 2
            elif words[i].startswith("-"):
                i += 1
            else:
                break
        if i < len(words) and words[i] == "push":
            return True
    return False


def push_probe(raw: str) -> str:
    """``PUSH\\n<cwd>`` when the Bash payload is a git push, else ''."""
    payload = json.loads(raw)
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not is_git_push(command):
        return ""
    cwd = payload.get("cwd")
    return "PUSH\n" + (cwd if isinstance(cwd, str) else "")


def _deny_json(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }})


_GUARDED_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent", "Task"}
_SAFE_SID = re.compile(r"[A-Za-z0-9_-]+\Z")


def _crash_decision(raw: str) -> str | None:
    """After an internal error: a mutating or guarded tool call from a session
    that orchestrates (it has a marker) is DENIED with a reason, never waved
    through — the guard may not fail open on the tools that can do anything.
    Self-contained (stdlib only: it must work when the package imports
    failed). Anything else stays fail-open (a hook crash must not wedge
    ordinary sessions)."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        tool = payload.get("tool_name")
        if not isinstance(tool, str) or not (tool in _GUARDED_TOOLS or tool.startswith("mcp__")):
            return None
        sid = payload.get("session_id")
        if not isinstance(sid, str) or not _SAFE_SID.match(sid):
            return None
        override = os.environ.get("CLAUDE_CONFIG_DIR")
        base = Path(override) if override else Path.home() / ".claude"
        if (base / "overseer" / ".orchestrating" / sid).exists():
            return _deny_json(
                f"GUARD: internal error while judging this {tool} call (denied, fail closed). "
                "Escape hatch: `release <card>`, \"guard\": false in .overseer/config.json, "
                "or OVERSEER_GUARD=off"
            )
    except Exception:  # noqa: BLE001
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    raw = ""
    try:
        raw = sys.stdin.read()
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        if args[:1] == ["--push-probe"]:
            out = push_probe(raw)
            if out:
                print(out)
            return 0
        decision = run(raw)
        if decision:
            print(json.dumps(decision))
    except Exception:  # noqa: BLE001 — see _crash_decision for what still denies
        out = _crash_decision(raw) if args[:1] != ["--push-probe"] else None
        if out:
            print(out)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
