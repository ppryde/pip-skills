"""Cheap PreToolUse entry point (WF-265 PR A, OL-7).

``cli.py pretool-hook`` imports the 94 KB CLI, PyYAML and every module, opens
the board read-write (schema pass, pragmas, ``git`` subprocesses) and only then
asks one question. This module answers the same question with the standard
library alone: ``json``, ``sqlite3``, ``os``, ``pathlib`` plus ``guard`` and
``shellscan``/``marker`` (themselves stdlib). No PyYAML, no ``cli.py``, no
``git``, no schema pass.

It also hosts the git-push probe used by ``prepush-snapshot.sh`` so that hook
needs one interpreter start (not up to three) to decide whether to act.

Contract unchanged from the CLI hook: print a JSON decision, or nothing; ANY
error means no output and exit 0 (fail open).
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):  # direct script invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import guard, marker, shellscan

GUARD_ENV = "OVERSEER_GUARD"
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def load_config(repo: Path | None) -> dict[str, object]:
    """``<repo>/.overseer/config.json`` then ``config.local.json`` (local
    wins) — the same precedence as ``config.load_config`` without its git
    lookup: the caller already holds the canonical root."""
    merged: dict[str, object] = {}
    if repo is None:
        return merged
    for name in ("config.json", "config.local.json"):
        try:
            data = json.loads((repo / ".overseer" / name).read_text() or "{}")
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            merged.update(data)
    return merged


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
    existed = directory.is_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)  # next call takes the shell fast path
    except OSError:
        pass
    boards = marker.read_boards(sid) if sid else []
    if sid and not boards and (not existed or not os.access(directory, os.W_OK)):
        # Upgrade window / unwritable marker dir: the shell had no marker to
        # trust, so ask the boards themselves (read-only, no git) once, and
        # leave a marker behind if there is something to guard.
        boards = marker.find_boards_for_session(sid)
        for board in boards:
            try:
                marker.write_marker(sid, board)
            except OSError as exc:
                print(f"overseer: cannot write the guard marker in {directory}: {exc}; "
                      "the full guard runs on every tool call until it is writable",
                      file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        raw = sys.stdin.read()
        if args[:1] == ["--push-probe"]:
            out = push_probe(raw)
            if out:
                print(out)
            return 0
        decision = run(raw)
        if decision:
            print(json.dumps(decision))
    except Exception:  # noqa: BLE001 — a failing PreToolUse hook must never block
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
