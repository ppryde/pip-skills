"""Overseer ledger CLI — the interface the ledger skill drives.

Single-writer by convention: only the orchestrating session calls this.
Cards live in ``board.db`` (see ``scripts/db.py``), the source of truth read
directly by the CLI, dashboard and ``resume``; every mutation writes the card
row, then reconciles (surfaces quarantined cards; ``ledger.md`` itself is
retired, WF-072). Sprints, usage, and knowledge remain file-based under the
``.workflow/`` state root.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

if __package__ in (None, ""):  # direct script invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import config, db, liveness  # noqa: E402
from scripts.calibration import BANDS, calibrate  # noqa: E402
from scripts.conflicts import find_conflicts  # noqa: E402
from scripts.index import rebuild_index  # noqa: E402
from scripts.models import (  # noqa: E402
    Card, CardParseError, LABEL_PALETTE_KEYS, PRIORITIES, format_tokens, parse_tokens,
)
from scripts.relations import would_cycle_depends, would_cycle_parent  # noqa: E402
from scripts.resume import format_report, handoff_data, handoff_report, resume_entries  # noqa: E402
from scripts.sprints import (  # noqa: E402
    SPRINT_STATUSES,
    Sprint,
    load_sprint,
    retro_rollup,
    rollup,
    save_sprint,
    sprint_path,
)
from scripts.store import (  # noqa: E402
    derive_repo_label,
    init_workflow,
    state_root,
)
from scripts.usage import append_usage, load_usage, summarise  # noqa: E402
from scripts.knowledge import (  # noqa: E402
    Fact,
    FactParseError,
    ensure_kb,
    find_fact_path,
    knowledge_root,
    load_fact,
    load_facts,
    mint_fact_id,
    rebuild_knowledge_index,
    retire_fact_file,
    save_fact,
)

DEFAULT_TTL = 30  # minutes — TTL fallback for reclaim_stale when census is down

_CONN_CACHE: dict[str, sqlite3.Connection] = {}


def _conn(repo_root: Path) -> sqlite3.Connection:
    """One cached ``board.db`` connection per resolved repo root, per process,
    for this module's own card operations (every ``_load``/``_sync`` call
    site, plus the direct ``db.*`` calls verbs make against a loaded card).

    ``main()`` closes every cached connection in its ``finally``. This cache
    does NOT cover the whole CLI invocation, though: the view modules
    (``scripts.board``, ``scripts.index``, ``scripts.resume``) each open
    their own short-lived ``db.connect(repo_root)`` connection by design —
    they're read-mostly report builders, not part of the single-writer card
    path this cache exists for. Those connections are plain locals with no
    explicit ``close()``; CPython's refcounting closes them (via
    ``sqlite3.Connection.__del__``) as soon as the enclosing function
    returns and the reference drops.
    """
    key = str(repo_root.resolve())
    conn = _CONN_CACHE.get(key)
    if conn is None:
        conn = db.connect(repo_root)
        _CONN_CACHE[key] = conn
    return conn


def _close_conns() -> None:
    for conn in _CONN_CACHE.values():
        conn.close()
    _CONN_CACHE.clear()


CARD_BODY_TEMPLATE = """## Goal
{goal}

## Plan
_(pending)_

## Decisions

## Review log

## Progress log

## Verification
"""

SPRINT_BODY_TEMPLATE = """## Goal
{goal}

## Cards
| Card | Complexity | Est | Actual | Status |
|---|---|---|---|---|

## Conflicts

## Retro
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _report_quarantined(quarantined: list[Path]) -> None:
    for path in quarantined:
        print(f"QUARANTINED: {path}", file=sys.stderr)


def _vigil_cli() -> Path | None:
    """Best-effort locate the sibling vigil plugin's CLI (soft dependency)."""
    here = Path(__file__).resolve()  # plugins/overseer/scripts/cli.py
    candidate = here.parent.parent.parent / "vigil" / "scripts" / "cli.py"
    return candidate if candidate.exists() else None


def _vigil_context(repo_root: Path) -> str | None:
    """Run `vigil context`; return its line, or None if vigil is absent/errors."""
    cli = _vigil_cli()
    if cli is None:
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(cli), "--root", str(repo_root), "context"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip()
    return line or None


def _context_footer(repo_root: Path) -> str:
    """`\\nctx NN%` when vigil is installed and reports a real percentage; else ''."""
    line = _vigil_context(repo_root)
    if line and line.startswith("ctx ") and line != "ctx unknown":
        return "\n" + line
    return ""


def _census_cli() -> Path | None:
    """Best-effort locate the sibling census plugin's CLI (soft dependency)."""
    here = Path(__file__).resolve()  # plugins/overseer/scripts/cli.py
    candidate = here.parent.parent.parent / "census" / "scripts" / "cli.py"
    return candidate if candidate.exists() else None


def _census_session_live(session_id: str) -> bool:
    """Is ``session_id`` live in census (fresh within its 90s staleness horizon)?

    census is a SOFT dependency, shelled via subprocess exactly like the
    dashboard backend's ``cli_client.run_census`` — overseer must not import
    census internals (design spec §3). Every failure path (plugin absent,
    timeout, non-zero exit, unparsable output, empty/missing entry) returns
    False, i.e. "treat the holder as stale": a claim must not wedge just
    because census is down.
    """
    cli = _census_cli()
    if cli is None:
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(cli), "read", "--session", session_id],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return False
    if not isinstance(data, dict) or not data:
        return False
    return not data.get("stale", True)


def _sync(repo_root: Path, card: Card) -> None:
    """Persist the card, then reconcile: surface any quarantined cards. No
    ledger is written (WF-072 retired ``ledger.md``; board.db is the sole
    source of truth).

    Known multi-session limitation (spec-accepted YAGNI, no locking):
    ``save_card`` upserts the whole card row, so a hook racing another
    session's CLI verb against the same card is last-write-wins for the
    *entire* card, not just checklist rows.
    """
    db.save_card(_conn(repo_root), card)
    quarantined = rebuild_index(repo_root, repo_root.resolve().name, _now())
    _report_quarantined(quarantined)


def _load(repo_root: Path, card_id: str) -> Card:
    card = db.load_card(_conn(repo_root), card_id)
    if card is None:
        raise FileNotFoundError(f"no card with id {card_id}")
    return card


def cmd_init(args: argparse.Namespace) -> int:
    """`overseer init [--central PATH] [--backup-dir PATH] [--yes]` —
    bootstraps the `.workflow/` state tree (as before) and, new
    here, writes the repo's `.overseer/` config pair:

    - `.overseer/config.json` (`backup_dir`) — committed, shared default.
    - `.overseer/config.local.json` (`central_dir`) — gitignored, per-machine
      (mirrors `config.py`'s local-wins precedence).

    Both files, and the `.gitignore` line for the local one, are written at
    the repo's CANONICAL main root (`repo_config_dir`'s resolution, via
    `derive_repo_root`) — even when `init` is run from a linked worktree.
    This must agree with where `prepush-snapshot.sh`'s opt-in gate looks for
    `config.json`: writing config at the canonical root but gitignoring at
    the worktree (or vice versa) leaves opt-in incoherent between worktrees.

    `--central`/`--backup-dir` skip the corresponding prompt; with neither
    flag AND no TTY (e.g. under pytest, or a script), the resolved default
    is accepted silently. `--yes` forces the default even on a TTY.
    """
    from scripts import config as cfg

    base = cfg.repo_config_dir(args.root)  # canonical main root's `.overseer/`
    base.mkdir(parents=True, exist_ok=True)

    default_central = str(cfg.central_root(args.root))
    default_backup_dir = ".overseer/backups"
    non_interactive = args.yes or not sys.stdin.isatty()
    central = args.central or (
        default_central if non_interactive
        else input(f"Central folder [{default_central}]: ") or default_central
    )
    backup_dir_value = args.backup_dir or (
        default_backup_dir if non_interactive
        else input(f"Backup dir [{default_backup_dir}]: ") or default_backup_dir
    )

    (base / "config.json").write_text(
        json.dumps({"backup_dir": backup_dir_value}, indent=2))
    (base / "config.local.json").write_text(
        json.dumps({"central_dir": central}, indent=2))

    # `base.parent` is the same canonical root `base` itself was resolved
    # against — never a linked worktree's own root — so the gitignore line
    # lands next to the config files it's ignoring one of.
    gitignore = base.parent / ".gitignore"
    line = ".overseer/config.local.json"
    text = gitignore.read_text() if gitignore.exists() else ""
    if line not in text.split("\n"):
        gitignore.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n")

    init_workflow(args.root)
    _conn(args.root)  # creates + one-time-imports the board.db
    rebuild_index(args.root, args.root.resolve().name, _now())

    print(f"initialised {state_root(args.root)} "
          f"(central={central} backup_dir={backup_dir_value})")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from scripts import backup, config
    if getattr(args, "print_dir", False):
        dest = Path(args.dir) if args.dir else config.backup_dir(args.root)
        print(str(dest.resolve()))
        return 0
    dest = Path(args.dir) if args.dir else None
    stats = backup.backup_board(args.root, dest)
    print(f"backed up {stats['cards']} cards, {stats['sprint_files']} sprints, "
          f"{stats['fact_files']} facts, {stats['usage_lines']} usage lines "
          f"-> {stats['dest']}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from scripts import backup
    src = Path(args.dir) if args.dir else None
    stats = backup.restore_board(args.root, src)
    print(f"restored: {stats['inserted']} inserted, {stats['updated']} updated, "
          f"{stats['skipped_older']} skipped-older, {stats['files_restored']} files, "
          f"{stats['files_skipped']} files-present")
    return 0


def _print_clear(args: argparse.Namespace, payload: dict, human: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload))
    else:
        print(human)


def cmd_clear(args: argparse.Namespace) -> int:
    import shutil

    from scripts import backup, config
    from scripts.db import board_db_path

    scope = args.scope
    label = derive_repo_label(args.root) or args.root.resolve().name

    # No board yet -> no-op (not an error).
    if not board_db_path(args.root).exists():
        removed = {"cards": 0} if scope == "cards" else {
            "folder": str(config.central_root(args.root)), "existed": False}
        _print_clear(
            args,
            {"scope": scope, "backup_path": None, "removed": removed,
             "label": label, "noop": True},
            human=f"no overseer board for {label!r}; nothing to clear",
        )
        return 0

    # Confirmation gate (the dashboard always passes --yes).
    if not args.yes:
        if sys.stdin.isatty():
            reply = input(
                f"Clear scope={scope} for {label!r}? Type the repo label to confirm: "
            ).strip()
            if reply != label:
                raise ValueError("confirmation did not match; aborted")
        else:
            raise ValueError("clear requires --yes for non-interactive use")

    # Backup first (recoverable). A failure here ABORTS the wipe.
    backup_path = None
    if not args.no_backup:
        try:
            backup_path = backup.backup_board(args.root)["dest"]
        except OSError as exc:
            raise ValueError(f"backup failed, aborting clear: {exc}") from exc

    if scope == "cards":
        conn = _conn(args.root)
        deleted = conn.execute("DELETE FROM cards").rowcount
        conn.commit()
        rebuild_index(args.root, args.root.resolve().name, _now())
        removed: dict = {"cards": deleted}
    else:  # scope == "repo"
        folder = config.central_root(args.root)
        _close_conns()  # drop cached conn before removing the folder under it
        existed = folder.exists()
        if existed:
            shutil.rmtree(folder)
        removed = {"folder": str(folder), "existed": existed}

    snap = f" (recovery snapshot: {backup_path})" if backup_path else ""
    _print_clear(
        args,
        {"scope": scope, "backup_path": backup_path, "removed": removed,
         "label": label, "noop": False},
        human=f"cleared scope={scope} for {label!r}{snap}",
    )
    return 0


def cmd_new_card(args: argparse.Namespace) -> int:
    conn = _conn(args.root)
    card_id = args.jira or args.linear or db.mint_id(conn)
    card = Card(
        id=card_id,
        title=args.title.strip(),
        status="planned",
        jira=args.jira,
        linear=args.linear,
        complexity=args.complexity,
        sprint=args.sprint,
        budget_estimate=parse_tokens(args.estimate),
        created=_today(),
        updated=_now(),
        repo=args.repo if args.repo else derive_repo_label(args.root),
        labels=[lb.strip() for lb in args.labels.split(",") if lb.strip()] if args.labels else [],
        body=CARD_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    # Insert-only (not `_sync`'s upsert path): a plain existence check here
    # would leave a TOCTOU window where two concurrent `new-card` calls that
    # mint/target the same id both pass the check and one silently
    # overwrites the other. `create_card` raises on the PK collision instead.
    try:
        db.create_card(conn, card)
    except sqlite3.IntegrityError:
        print(f"error: card {card_id} already exists", file=sys.stderr)
        return 1
    _report_quarantined(rebuild_index(args.root, args.root.resolve().name, _now()))
    print(card.id)
    return 0


def cmd_set_stage(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.set_stage(args.stage, _now())
    card.ack_claim()  # work verb — design spec §3 ack list
    _sync(args.root, card)
    print(f"{card.id} → {args.stage}")
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.block(args.reason, _now())
    card.ack_claim()  # work verb — design spec §3 ack list
    _sync(args.root, card)
    print(f"{card.id} blocked: {args.reason}")
    return 0


def cmd_unblock(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.unblock(_now())
    _sync(args.root, card)
    print(f"{card.id} → {card.status}")
    return 0


def _close(args: argparse.Namespace, verb: str) -> int:
    card = _load(args.root, args.card_id)
    card.complete(_now()) if verb == "done" else card.abandon(_now())
    db.archive_card(_conn(args.root), card)
    rebuild_index(args.root, args.root.resolve().name, _now())
    print(f"{card.id} {card.status}, archived")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    return _close(args, "done")


def cmd_abandon(args: argparse.Namespace) -> int:
    return _close(args, "abandon")


def cmd_set_field(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    if args.branch:
        card.branch = args.branch
    if args.worktree:
        card.worktree = args.worktree
    if args.pr:
        card.pr = args.pr
    if args.touches is not None:
        card.touches = [t.strip() for t in args.touches.split(",") if t.strip()]
    if args.labels is not None:
        card.labels = [lb.strip() for lb in args.labels.split(",") if lb.strip()]
    if args.repo is not None:
        card.repo = args.repo if args.repo else None
    if args.order is not None:
        card.order = args.order
    if args.priority is not None:
        if args.priority == "":
            card.priority = None
        else:
            if args.priority not in PRIORITIES:
                print(f"error: unknown priority: {args.priority!r}", file=sys.stderr)
                return 1
            card.priority = args.priority
    if args.parent is not None:
        if args.parent == "":
            card.parent = None
        else:
            cards, _ = db.load_live_cards(_conn(args.root))
            if args.parent not in {c.id for c in cards}:
                print(f"error: no live card {args.parent}", file=sys.stderr)
                return 1
            if would_cycle_parent(cards, args.card_id, args.parent):
                print(f"error: parent {args.parent} would create a cycle",
                      file=sys.stderr)
                return 1
            card.parent = args.parent
    if args.title is not None:
        if not args.title.strip():
            print("error: title cannot be empty", file=sys.stderr)
            return 1
        card.title = args.title.strip()
    if args.body is not None:
        card.body = args.body
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} updated")
    return 0


CHECKLIST_STATUSES = ("pending", "in_progress", "completed", "deleted")


def _apply_checklist(
    repo_root: Path, card_id: str, task_id: str, subject: str | None, status: str
) -> int:
    """Upsert or delete one checklist entry (keyed by ``task_id``) on ``card_id``.

    The single-writer path shared by ``cmd_checklist`` (CLI verb) and the
    ``checklist-sync-hook`` verb — both call this, and only this, to touch a
    card's checklist. Returns 0 on success, including an idempotent replay
    (no write) and a delete of an already-absent entry. Returns 1 when a NEW
    entry is being created with no ``subject`` given — the caller decides how
    loudly to surface that (CLI: exit 1 with a message; hook: silent no-op,
    the checklist simply lags). Propagates ``FileNotFoundError`` /
    ``CardParseError`` from an unknown or corrupt card — the CLI surfaces
    those via ``main``; the hook catches and swallows them.
    """
    card = _load(repo_root, card_id)
    checklist: list[dict] = card.checklist
    existing_index = next(
        (i for i, entry in enumerate(checklist) if entry["task"] == task_id), None
    )

    if status == "deleted":
        if existing_index is not None:
            card.checklist = [e for i, e in enumerate(checklist) if i != existing_index]
            card.updated = _now()
            _sync(repo_root, card)
        return 0

    if existing_index is None:
        if not subject:
            return 1
        checklist.append({"task": task_id, "subject": subject, "status": status})
        card.updated = _now()
        _sync(repo_root, card)
        return 0

    entry = checklist[existing_index]
    new_subject = subject if subject else entry["subject"]
    if entry["subject"] == new_subject and entry["status"] == status:
        return 0
    checklist[existing_index] = {"task": task_id, "subject": new_subject, "status": status}
    card.updated = _now()
    _sync(repo_root, card)
    return 0


def cmd_checklist(args: argparse.Namespace) -> int:
    # Capture pre-image existence for reporting only — `_apply_checklist`'s
    # behaviour and exit codes are unchanged; this just tells a real delete
    # apart from a no-op delete of an already-absent entry.
    existed = (
        _existing_checklist_status(args.root, args.card_id, args.task) is not None
        if args.status == "deleted"
        else None
    )
    result = _apply_checklist(args.root, args.card_id, args.task, args.subject, args.status)
    if result == 1:
        print(
            f"error: new checklist entry for task {args.task} requires --subject",
            file=sys.stderr,
        )
        return 1
    if args.status == "deleted":
        if existed:
            print(f"{args.card_id} checklist: task {args.task} removed")
        else:
            print(f"{args.card_id} checklist: task {args.task} already absent")
    else:
        print(f"{args.card_id} checklist: task {args.task} → {args.status}")
    return 0


# --- checklist-sync-hook: PostToolUse (TaskCreate|TaskUpdate) backend ----------
#
# Wires Claude Code's native task list into a card's `checklist:` frontmatter.
# See docs/superpowers/specs/2026-07-12-overseer-task-checklist-sync-design.md
# §3/§6 and docs/research/2026-07-12-claude-code-task-system.md. Follows
# vigil's house pattern for hook backends (`_read_hook_payload`, `_hook_root`).

TASK_LIST_ID_ENV = "CLAUDE_CODE_TASK_LIST_ID"
TASK_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"


def _read_hook_payload() -> dict[str, object]:
    """Read and parse the hook's stdin JSON payload exactly once.

    Every hook invocation is a fresh process reading its own stdin once.
    Returns ``{}`` on unreadable or non-object stdin — callers fall back to
    defaults rather than raising.
    """
    try:
        payload = json.loads(sys.stdin.read())
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _hook_root(payload: dict[str, object], args: argparse.Namespace) -> Path:
    cwd = payload.get("cwd")
    return Path(cast(str, cwd)) if isinstance(cwd, str) and cwd else args.root


def _hook_session_id(payload: dict[str, object], args: argparse.Namespace) -> str | None:
    """Session id for task-list resolution: hook stdin's ``session_id`` field
    wins (every Claude Code hook payload carries one); falls back to the CLI's
    optional ``--session-id`` for scripted/manual invocations."""
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    fallback: str | None = args.session_id
    return fallback


def _task_config_dir() -> Path:
    """The active Claude config dir — same account-isolation boundary census
    uses. ``$CLAUDE_CONFIG_DIR`` if set, else ``~/.claude``."""
    override = os.environ.get(TASK_CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def _task_list_dir(config_dir: Path, session_id: str | None) -> Path:
    """Named list when ``$CLAUDE_CODE_TASK_LIST_ID`` is set; else this
    session's scoped list (``session-<first 8 chars of session_id>``)."""
    list_id = os.environ.get(TASK_LIST_ID_ENV)
    if list_id:
        return config_dir / "tasks" / list_id
    return config_dir / "tasks" / f"session-{(session_id or '')[:8]}"


def _task_file_card_id(task_id: str, session_id: str | None) -> str | None:
    """Recover a task's card id from its on-disk task file.

    None if the file is unreadable, absent (pruned, or a session-scoped task
    that already completed — those files are deleted the instant they
    complete), or malformed — callers fall back to the card-scan.
    """
    task_path = _task_list_dir(_task_config_dir(), session_id) / f"{task_id}.json"
    try:
        data = json.loads(task_path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    card_id = metadata.get("card")
    return card_id if isinstance(card_id, str) and card_id else None


def _scan_for_card_id(repo_root: Path, task_id: str) -> str | None:
    """Fallback card-id recovery: scan live cards' existing checklists for an
    entry keyed by ``task_id``. Used when the task file is already gone.

    Accepted ambiguity: task ids are only unique per task list, so two
    un-bootstrapped sessions (each on its own session-scoped list, see
    ``_task_list_dir``) can mint the same id, and this scan returns whichever
    live card's checklist has a matching entry first. Bootstrapping a named
    ``CLAUDE_CODE_TASK_LIST_ID`` shares one list across sessions and
    eliminates the collision.
    """
    cards, _ = db.load_live_cards(_conn(repo_root))
    for card in cards:
        if any(entry.get("task") == task_id for entry in card.checklist):
            return card.id
    return None


def _existing_checklist_status(repo_root: Path, card_id: str, task_id: str) -> str | None:
    """The current status of ``task_id``'s entry on ``card_id``, or None."""
    try:
        card = _load(repo_root, card_id)
    except FileNotFoundError:
        return None
    for entry in card.checklist:
        if entry.get("task") == task_id:
            return str(entry.get("status", "pending"))
    return None


def cmd_checklist_sync_hook(args: argparse.Namespace) -> int:
    """PostToolUse (TaskCreate|TaskUpdate) hook backend.

    Projects task lifecycle events into the owning card's ``checklist:``
    frontmatter via ``_apply_checklist`` — the same single-writer path as the
    ``checklist`` CLI verb. Never raises; every failure path (malformed
    stdin, missing fields, an orphan task, an unknown card, a store error) is
    silent success — the checklist simply lags, the agent's own tasks are
    never blocked (spec §6).
    """
    try:
        payload = _read_hook_payload()
        repo_root = _hook_root(payload, args)
        if not state_root(repo_root).is_dir():
            return 0

        tool_name = payload.get("tool_name")
        raw_input = payload.get("tool_input")
        tool_input = raw_input if isinstance(raw_input, dict) else {}
        raw_response = payload.get("tool_response")
        tool_response = raw_response if isinstance(raw_response, dict) else {}

        if tool_name == "TaskCreate":
            raw_metadata = tool_input.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            card_id = metadata.get("card")
            if not isinstance(card_id, str) or not card_id:
                return 0  # orphan task — not card work
            raw_task = tool_response.get("task")
            task = raw_task if isinstance(raw_task, dict) else {}
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id:
                return 0
            subject = tool_input.get("subject")
            subject = subject if isinstance(subject, str) else None
            _apply_checklist(repo_root, card_id, task_id, subject, "pending")
            return 0

        if tool_name == "TaskUpdate":
            task_id = tool_input.get("taskId")
            if not isinstance(task_id, str) or not task_id:
                return 0

            status: str | None = None
            status_change = tool_response.get("statusChange")
            if isinstance(status_change, dict):
                to_status = status_change.get("to")
                if isinstance(to_status, str) and to_status:
                    status = to_status

            raw_subject = tool_input.get("subject")
            subject = raw_subject if isinstance(raw_subject, str) else None

            if status is None and subject is None:
                return 0  # neither a status transition nor a subject change
            if status is not None and status not in CHECKLIST_STATUSES:
                return 0  # not overseer's vocabulary

            card_id = _task_file_card_id(task_id, _hook_session_id(payload, args))
            if card_id is None:
                card_id = _scan_for_card_id(repo_root, task_id)
            if card_id is None:
                return 0  # unresolved — lag, not breakage

            if status is None:
                # subject-only update: preserve the entry's existing status
                status = _existing_checklist_status(repo_root, card_id, task_id)
                if status is None:
                    return 0  # no existing entry to preserve a status from

            _apply_checklist(repo_root, card_id, task_id, subject, status)
            return 0

        return 0
    except Exception:
        return 0


def cmd_depends(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    cards, _ = db.load_live_cards(_conn(args.root))
    ids = {c.id for c in cards}
    if args.on:
        if args.on == args.card_id:
            print("error: a card cannot depend on itself", file=sys.stderr)
            return 1
        if args.on not in ids:
            print(f"error: no live card {args.on}", file=sys.stderr)
            return 1
        if would_cycle_depends(cards, args.card_id, args.on):
            print(f"error: depending on {args.on} would create a cycle",
                  file=sys.stderr)
            return 1
        if args.on not in card.depends_on:
            card.depends_on.append(args.on)
    if args.off and args.off in card.depends_on:
        card.depends_on.remove(args.off)
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} depends_on: {', '.join(card.depends_on) or '(none)'}")
    return 0


def cmd_park(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.park(_now())
    _sync(args.root, card)
    print(f"{card.id} parked")
    return 0


def cmd_unpark(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.unpark(_now())
    _sync(args.root, card)
    print(f"{card.id} → {card.status}")
    return 0


def cmd_pull_children(args: argparse.Namespace) -> int:
    """`overseer pull-children <card_id>` — F9/WF-066: moves every LIVE
    child of an epic into the parent's board column in one shot.

    "Column" here is (stage, status) together, mirroring how `set-stage`
    and `unblock` derive it for a single card: if the parent has a stage,
    each child is stamped into that same stage via `set_stage` (which also
    flips status to "in-flight" and clears any `blocked_on`, same as
    `set-stage` does for one card). If the parent has NO stage, there is no
    stage to copy — but the parent's STATUS still determines the lane, and
    is copied onto the child rather than hardcoded. This matters because a
    stage-less parent isn't always "planned": `park()` has no stage
    precondition, so a parent can be `parked` (or `blocked`) with
    `stage=None` too, and a hardcoded "planned" would silently strand
    children in Backlog while the parent sits in a different lane
    (board `layout.ts` places stage-less cards by status: planned/blocked
    → Backlog, parked → Parked, independently).

    Defensive-only fallback: `_load` doesn't restrict to live cards, so a
    caller invoking this against an already-archived (done/abandoned)
    parent must not propagate a terminal status onto still-live children —
    falls back to "planned" in that case instead.

    Archived cards (done/abandoned) never appear in `load_live_cards`, so
    they're skipped without any special-casing. Batches the writes (one
    `db.save_card` per child) and runs a single `rebuild_index` at the end
    rather than looping `_sync`, since a naive per-child `_sync` would
    rebuild the index N times for one logical move.
    """
    parent = _load(args.root, args.card_id)
    cards, _ = db.load_live_cards(_conn(args.root))
    children = [c for c in cards if c.parent == args.card_id]
    if not children:
        print(f"no live children of {parent.id}")
        return 0
    now = _now()
    for child in children:
        if parent.stage:
            child.set_stage(parent.stage, now)
        else:
            child.stage = None
            child.status = (
                parent.status if parent.status not in ("done", "abandoned")
                else "planned"
            )
            child.blocked_on = parent.blocked_on if child.status == "blocked" else None
            child.updated = now
        db.save_card(_conn(args.root), child)
    quarantined = rebuild_index(args.root, args.root.resolve().name, now)
    _report_quarantined(quarantined)
    print(f"pulled {len(children)} children into {parent.id}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    """`overseer claim <id> --session <sid> [--force]` — design spec §3.

    A pure stamp, no delivery side effects. Unknown card -> propagates
    FileNotFoundError to `main` (exit 1), same as every other verb. Refuses
    (exit 1) only when the existing holder is a DIFFERENT, live session and
    `--force` was not given; a stale/absent holder is displaced with a note,
    and `--force` displaces a live holder too. Re-claiming by the same
    session that already holds it is treated as an ordinary (re-)stamp — no
    liveness check against itself.

    The genuinely-unclaimed path (no prior holder at all) is the one case
    where two sessions can race each other for the very same card: both may
    observe `prior_holder is None` before either has written. That path uses
    `db.claim_card(..., force=args.force)` — an atomic `UPDATE ... WHERE
    claimed_by IS NULL` compare-and-swap when `--force` is not given — so
    only one writer's UPDATE can land; the loser is told the card was
    already claimed rather than silently overwriting the winner. Every other
    branch below (self-restamp, live-displace, stale-displace) targets a
    card this CLI invocation has already determined has a specific existing
    `claimed_by` value it means to overwrite, so those keep the unconditional
    `force=True` stamp — a `WHERE claimed_by IS NULL` guard would never match
    and would wrongly report those as lost races.
    """
    conn = _conn(args.root)
    now = _now()
    # Load the target FIRST: an unknown id must fail fast with
    # "no card with id ..." without paying for the board-wide reclaim sweep
    # below. Capture the prior holder before the sweep runs, since the sweep
    # may itself clear this very card's stale claim — reading claimed_by
    # afterwards would silently hide that a displacement happened.
    card = _load(args.root, args.card_id)
    prior_holder = card.claimed_by
    reclaimed = db.reclaim_stale(conn, liveness.live_session_ids(), DEFAULT_TTL, now)
    note = None
    if prior_holder and prior_holder != args.session:
        if card.id in reclaimed:
            # The sweep already cleared this claim as stale — no live check,
            # no --force gate needed, just report the displacement.
            live = False
        else:
            live = _census_session_live(prior_holder)
            if live and not args.force:
                print(
                    f"error: {card.id} already claimed by {prior_holder} (live)"
                    " — use --force to override",
                    file=sys.stderr,
                )
                return 1
        kind = "live" if live else "stale"
        note = f"note: displaced {kind} claim held by {prior_holder}"
        # A specific existing holder is being intentionally overwritten
        # (displacement, already authorised above) — unconditional stamp.
        db.claim_card(conn, card.id, args.session, now, force=True)
    elif prior_holder == args.session:
        # Idempotent re-stamp by the session that already holds it — also
        # targets a non-NULL claimed_by, so this must stay unconditional too.
        db.claim_card(conn, card.id, args.session, now, force=True)
    else:
        # Genuinely unclaimed (post-sweep): close the race window with an
        # atomic compare-and-swap. `--force` always wins outright (matches
        # its displace-a-live-holder semantics elsewhere); otherwise only one
        # concurrent claimer's UPDATE can match `WHERE claimed_by IS NULL`.
        won = db.claim_card(conn, card.id, args.session, now, force=args.force)
        if not won:
            current = db.load_card(conn, card.id)
            holder = current.claimed_by if current else None
            print(
                f"error: {card.id} already claimed by {holder}"
                " — use --force to override",
                file=sys.stderr,
            )
            return 1
    _report_quarantined(rebuild_index(args.root, args.root.resolve().name, now))
    if note:
        print(note)
    print(f"{card.id} claimed by {args.session}")
    return 0


def cmd_unclaim(args: argparse.Namespace) -> int:
    """`overseer unclaim <id>` — clears all claim fields, idempotent (exit 0
    even when already unclaimed)."""
    card = _load(args.root, args.card_id)
    card.unclaim(_now())
    _sync(args.root, card)
    print(f"{card.id} unclaimed")
    return 0


def _mark_claim_nudged(repo_root: Path, card_id: str) -> bool:
    """Stamp `claim_nudged = true` on `card_id` — the single-writer path
    shared by the `claim-nudged` CLI verb and `claim-stop-hook` (design spec
    §4, WF-022). Returns False (no write) when the card is unknown, corrupt,
    or no longer claimed (a race with `unclaim`/a fresh `claim`) — never
    raises, so a hook calling this directly stays quarantine-safe.
    """
    try:
        card = _load(repo_root, card_id)
    except (FileNotFoundError, CardParseError):
        return False
    if not card.claimed_by:
        return False
    card.claim_nudged = True
    card.updated = _now()
    _sync(repo_root, card)
    return True


def cmd_claim_nudged(args: argparse.Namespace) -> int:
    """`overseer claim-nudged <id>` — for the WF-022 Stop hook to shell after
    it has already blocked once for an unacked claim (design spec §4).
    """
    if _mark_claim_nudged(args.root, args.card_id):
        print(f"{args.card_id} claim_nudged")
    return 0


# --- claim-stop-hook / claim-prompt-hook: turn-boundary claim delivery --------
#
# Design spec §4 (docs/superpowers/specs/2026-07-13-overseer-card-claim-design.md).
# Both hooks read `session_id` from their stdin payload, scan live cards for
# `claimed_by == session_id && !claim_acked`, and follow the checklist-sync
# quarantine-safe shape: every failure path exits 0 with no output.


def _unacked_claims(repo_root: Path, session_id: str) -> list[Card]:
    """Live cards claimed by `session_id` and not yet acked, in the store's
    deterministic (id-sorted) order — the "first" claim for nudge purposes is
    whichever sorts first."""
    cards, _ = db.load_live_cards(_conn(repo_root))
    return [c for c in cards if c.claimed_by == session_id and not c.claim_acked]


def cmd_claim_stop_hook(args: argparse.Namespace) -> int:
    """Stop hook backend (design spec §4). At the turn boundary: an unacked
    claim addressed to this session means work was handed over while it was
    busy.

    - No unacked claims → silent, no output.
    - First nudge this cycle (`!claim_nudged && !stop_hook_active`) →
      `decision: block` with the pickup reason, and stamps `claim_nudged` via
      `_mark_claim_nudged` (direct call, same single-writer path the CLI verb
      uses) so the next Stop passes clean once the pickup acks. Multiple
      unacked claims: only the first (id order) is nudged/blocked on; the
      rest are named in the reason line.
    - Already nudged, or `stop_hook_active` (a Stop hook already blocked this
      cycle) → non-blocking `systemMessage`, stop stands.

    Every failure path exits 0 with no output — never breaks the stop.
    """
    try:
        payload = _read_hook_payload()
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return 0
        repo_root = _hook_root(payload, args)
        if not state_root(repo_root).is_dir():
            return 0
        unacked = _unacked_claims(repo_root, session_id)
        if not unacked:
            return 0
        first, rest = unacked[0], unacked[1:]
        stop_hook_active = bool(payload.get("stop_hook_active"))
        if not first.claim_nudged and not stop_hook_active:
            _mark_claim_nudged(repo_root, first.id)
            reason = (
                f"Claimed for you from the dashboard: pick up {first.id} — "
                "run resume and work the card."
            )
            if rest:
                reason += f" (also unacknowledged: {', '.join(c.id for c in rest)})"
            print(json.dumps({"decision": "block", "reason": reason}))
            return 0
        print(json.dumps({
            "systemMessage": f"overseer: {first.id} is claimed for this "
                              "session and unacknowledged",
        }))
        return 0
    except Exception:
        return 0


def cmd_claim_prompt_hook(args: argparse.Namespace) -> int:
    """UserPromptSubmit hook backend (design spec §4). Covers the attended
    case: injects a one-line notice when unacked claims addressed to this
    session exist, so a human mid-conversation doesn't need to wait for a
    turn end. Never blocks; repeats every prompt until a work verb acks the
    claim. Every failure path exits 0 with no output.
    """
    try:
        payload = _read_hook_payload()
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return 0
        repo_root = _hook_root(payload, args)
        if not state_root(repo_root).is_dir():
            return 0
        unacked = _unacked_claims(repo_root, session_id)
        if not unacked:
            return 0
        event_name = payload.get("hook_event_name")
        if not isinstance(event_name, str) or not event_name:
            event_name = "UserPromptSubmit"
        notice = (
            "Cards claimed for this session from the dashboard: "
            f"{', '.join(c.id for c in unacked)} — run resume / pick up."
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": notice,
            },
        }))
        return 0
    except Exception:
        return 0


def cmd_log_progress(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    tokens = parse_tokens(args.tokens) or 0
    card.log_progress(args.note, tokens, _now())
    card.ack_claim()  # work verb — design spec §3 ack list
    _sync(args.root, card)
    if card.tripwire_breached:
        actual = format_tokens(card.budget_actual)
        estimate = format_tokens(card.budget_estimate)
        print(
            f"TRIPWIRE: {card.id} at {actual} vs estimate {estimate} — "
            "stop this card and escalate to the user",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_log_review(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.log_review(args.stage, args.reviewers, args.verdict, _now())
    card.ack_claim()  # work verb — design spec §3 ack list
    _sync(args.root, card)
    print(f"{card.id} {args.stage} round {card.review_rounds(args.stage)} logged")
    return 0


def cmd_new_sprint(args: argparse.Namespace) -> int:
    # Ensure the one-time `.workflow/` -> central migration guard has run
    # before this verb creates/touches central state directly (bypassing
    # `_load`/`_sync`'s usual `_conn` call). On an upgraded repo, this verb
    # running FIRST would otherwise write straight into an unmigrated
    # central folder and collide with legacy `.workflow/sprints/` data that
    # `db.connect`'s migration would have imported.
    _conn(args.root)
    sprint = Sprint(
        id=args.sprint_id,
        status="planned",
        budget_estimate=parse_tokens(args.estimate),
        started=_today(),
        body=SPRINT_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    save_sprint(state_root(args.root), sprint)
    print(sprint.id)
    return 0


def cmd_rollup_sprint(args: argparse.Namespace) -> int:
    root = state_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    cards, quarantined = db.load_live_cards(_conn(args.root))
    _report_quarantined(quarantined)
    save_sprint(root, rollup(sprint, cards))
    print(f"{args.sprint_id} rolled up")
    return 0


def cmd_set_sprint_status(args: argparse.Namespace) -> int:
    root = state_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    sprint.status = args.status
    if args.status == "closed":
        live, quarantined = db.load_live_cards(_conn(args.root))
        _report_quarantined(quarantined)
        sprint = retro_rollup(sprint, live + db.load_archived_cards(_conn(args.root)))
    save_sprint(root, sprint)
    print(f"{sprint.id} → {args.status}")
    return 0


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    """``ledger.md`` is retired (WF-072) — board.db is the source of truth
    and the CLI/dashboard/resume all read it directly. This verb now just
    reconciles: it surfaces quarantined (corrupt) cards and removes any
    stale ``ledger.md`` left over from before the retirement."""
    quarantined = rebuild_index(args.root, args.root.resolve().name, _now())
    _report_quarantined(quarantined)
    print("reconciled — quarantined cards (if any) reported above")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    _, quarantined = db.load_live_cards(_conn(args.root))
    _report_quarantined(quarantined)
    entries = resume_entries(args.root, session_id=args.session_id)
    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        print(format_report(entries, session_id=args.session_id) + _context_footer(args.root))
    return 0


def cmd_conflicts(args: argparse.Namespace) -> int:
    cards, quarantined = db.load_live_cards(_conn(args.root))
    _report_quarantined(quarantined)
    if args.sprint:
        cards = [c for c in cards if c.sprint == args.sprint]
    conflicts = find_conflicts(cards)
    if args.json:
        print(json.dumps([[a, b, paths] for a, b, paths in conflicts], indent=2))
        return 0
    if not conflicts:
        print("No conflicts.")
        return 0
    for a, b, paths in conflicts:
        print(f"{a} ~ {b}: {', '.join(paths)}")
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    data = handoff_data(args.root)
    for path in data["quarantined"]:
        print(f"QUARANTINED: {path}", file=sys.stderr)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(handoff_report(args.root, data) + _context_footer(args.root))
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    from scripts.board import board_data
    data = board_data(args.root)
    _report_quarantined([Path(p) for p in data["quarantined"]])
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        card_count = len(data["cards"])
        sprint_count = len(data["sprints"])
        print(f"{card_count} cards, {sprint_count} sprints")
    return 0


def _read_repo_root_meta(db_path: Path) -> "str | None":
    """Best-effort read-only peek at a board.db's ``meta['repo_root']`` for
    the ``repos`` discovery verb. Opened read-only (``mode=ro``) so
    discovery never creates, locks, or schema-touches a board it's merely
    listing. Never raises — a corrupt, mid-write, or otherwise unreadable
    board.db is simply skipped, same quarantine-safe spirit as the rest of
    this module's report-building verbs.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return None
    try:
        return db.get_meta(conn, "repo_root")
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def cmd_repos(args: argparse.Namespace) -> int:
    """`overseer repos --json` — enumerate every discoverable board at
    `$CLAUDE_CONFIG_DIR/overseer/*/board.db` (one per repo, per the
    per-repo board.db migration). Powers the dashboard's repo switcher.

    A board is skipped when its `meta['repo_root']` is missing/None (an
    older board, or one whose repo_root was never derivable — e.g. no git)
    or when that recorded root no longer exists on disk (repo deleted or
    moved since the board was written). Output is a JSON list of
    `{"label": ..., "root": ...}`, sorted by label.
    """
    config_dir = config._config_dir()
    overseer_dir = config_dir / "overseer"
    results: list[dict[str, str]] = []
    if overseer_dir.is_dir():
        for label_dir in overseer_dir.iterdir():
            if not label_dir.is_dir():
                continue
            db_path = label_dir / "board.db"
            if not db_path.is_file():
                continue
            root_str = _read_repo_root_meta(db_path)
            if not root_str:
                continue
            if not Path(root_str).exists():
                continue
            # Display label comes from the repo root, never the folder name —
            # the default folder is now `<label>-<hash>` (see
            # config.central_root), so `label_dir.name` would leak the hash.
            label = derive_repo_label(Path(root_str)) or Path(root_str).name
            results.append({"label": label, "root": root_str})
    results.sort(key=lambda r: r["label"])
    if args.json:
        print(json.dumps(results))
    else:
        for r in results:
            print(f"{r['label']}: {r['root']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    # db.load_card already spans both live and archived rows, so a single
    # `_load` covers what used to be a live lookup plus an archive-dir glob.
    card = _load(args.root, args.id)
    data = {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "stage": card.stage,
        "order": card.order,
        "complexity": card.complexity,
        "priority": card.priority,
        "jira": card.jira,
        "linear": card.linear,
        "sprint": card.sprint,
        "parent": card.parent,
        "branch": card.branch,
        "worktree": card.worktree,
        "pr": card.pr,
        "touches": card.touches,
        "depends_on": card.depends_on,
        "labels": card.labels,
        "links": card.links,
        "budget": {
            "estimate": card.budget_estimate,
            "actual": card.budget_actual,
        },
        "created": card.created,
        "updated": card.updated,
        "blocked_on": card.blocked_on,
        "checklist": card.checklist,
        "repo": card.repo,
        "claimed_by": card.claimed_by,
        "claimed_at": card.claimed_at,
        "claim_acked": card.claim_acked,
        "sections": card.sections,
        "body": card.body,
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print(f"{card.id} — {card.title} [{card.status}/{card.stage or '-'}]")
    for header in card.sections:
        print(f"  {header or '(preamble)'}")
    return 0


def cmd_log_usage(args: argparse.Namespace) -> int:
    # Same migration-ordering guard as `cmd_new_sprint` — this verb appends
    # straight to central's `usage.jsonl` without going through `_load`/
    # `_sync`, so it must trigger the one-time `.workflow/` import itself
    # before it can run first on an upgraded repo.
    _conn(args.root)
    entry = {
        "ts": _now(),
        "card": args.card_id,
        "role": args.role,
        "stage": args.stage,
        "tier": args.tier,
        "tokens": parse_tokens(args.tokens) or 0,
        "round": args.round,
    }
    append_usage(state_root(args.root), entry)
    print(f"usage logged: {args.card_id} {args.role} {args.tokens}")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    entries, skipped = load_usage(state_root(args.root))
    if skipped:
        print(f"warning: {skipped} corrupt usage line(s) skipped", file=sys.stderr)
    summary = summarise(entries, args.card)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    if not summary["total"]:
        print("No usage recorded.")
        return 0
    lines = [f"# Usage — total: {format_tokens(summary['total'])}", "", "## By role"]
    lines += [f"- {r}: {format_tokens(t)}" for r, t in sorted(summary["by_role"].items())]
    lines += ["", "## By card"]
    lines += [f"- {c}: {format_tokens(t)}" for c, t in sorted(summary["by_card"].items())]
    print("\n".join(lines))
    return 0


def cmd_calibration(args: argparse.Namespace) -> int:
    cards = db.load_archived_cards(_conn(args.root))
    report = calibrate(cards)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    total = sum(report["bands"][b]["count"] for b in BANDS)
    if not total:
        if report["skipped"]:
            print(
                f"{report['skipped']} completed card(s) skipped "
                "(no estimate or no actual); no calibratable samples."
            )
        else:
            print("No completed cards to calibrate from.")
        return 0
    lines = ["# Calibration (actual ÷ estimate)", ""]
    for b in BANDS:
        band = report["bands"][b]
        if not band["count"]:
            lines.append(f"- {b}: no samples")
            continue
        mult = f", suggest ×{band['multiplier']}" if band["multiplier"] else ""
        lines.append(
            f"- {b}: n={band['count']}, median {band['median']}, "
            f"mean {band['mean']}{mult}"
        )
    if report["skipped"]:
        lines.append(f"\n_{report['skipped']} completed card(s) skipped "
                     "(no estimate or no actual)._")
    print("\n".join(lines))
    return 0


def cmd_add_fact(args: argparse.Namespace) -> int:
    # Same migration-ordering guard as `cmd_new_sprint`/`cmd_log_usage` —
    # `ensure_kb` creates central's `knowledge/` tree directly, so it must
    # not run ahead of the one-time `.workflow/` import on an upgraded repo.
    _conn(args.root)
    kb = knowledge_root(args.root)
    ensure_kb(kb)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    fact = Fact(
        id=mint_fact_id(kb),
        statement=args.statement,
        tags=tags,
        source=args.source,
        created=_today(),
        verified=_today(),
        status="active",
        body=args.body or "",
    )
    save_fact(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(fact.id)
    return 0


def cmd_verify_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    fact = load_fact(find_fact_path(kb, args.fact_id))
    fact.verified = _today()
    fact.status = "active"
    save_fact(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(f"{fact.id} verified {fact.verified}")
    return 0


def cmd_retire_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    fact = load_fact(find_fact_path(kb, args.fact_id))
    fact.status = "retired"
    fact.superseded_by = args.superseded_by
    retire_fact_file(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(f"{fact.id} retired")
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    facts, quarantined = load_facts(kb)
    _report_quarantined(quarantined)
    today = _today()
    rows = []
    for f in facts:
        effective = f.effective_status(today)
        if args.tag and args.tag not in f.tags:
            continue
        if args.stale and effective != "stale":
            continue
        rows.append({
            "id": f.id,
            "statement": f.statement,
            "tags": f.tags,
            "verified": f.verified,
            "status": effective,
        })
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No stale facts." if args.stale else "No facts.")
        return 0
    for r in rows:
        mark = " [STALE]" if r["status"] == "stale" else ""
        tags = ", ".join(r["tags"]) or "no tags"
        print(f"{r['id']} ({tags}){mark}: {r['statement']}")
    return 0


# --- label-color: editable colour registry (F10, WF-067) -----------------
#
# `color_key` validity is enforced by argparse's `choices=LABEL_PALETTE_KEYS`
# on the `set` subparser (see build_parser) — an invalid key is a usage
# error, which `main()` already turns into exit 1, matching every other
# choice-validated positional in this file (e.g. `set-sprint-status`).


def cmd_label_color_set(args: argparse.Namespace) -> int:
    db.set_label_color(_conn(args.root), args.name, args.color_key)
    print(f"{args.name} -> {args.color_key}")
    return 0


def cmd_label_color_clear(args: argparse.Namespace) -> int:
    db.clear_label_color(_conn(args.root), args.name)
    print(f"{args.name} cleared")
    return 0


def cmd_label_color_list(args: argparse.Namespace) -> int:
    colors = db.load_label_colors(_conn(args.root))
    if args.json:
        print(json.dumps(colors, indent=2))
        return 0
    if not colors:
        print("No label colours registered.")
        return 0
    for name in sorted(colors):
        print(f"{name}: {colors[name]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overseer", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--session-id", dest="session_id", default=None,
        help="task-list lookup key for this session (hook stdin's session_id "
             "wins when invoked as a hook; used for scripted/manual calls)",
    )
    parser.add_argument(
        "--remote",
        default=os.environ.get("OVERSEER_REMOTE"),
        help="Forward this command to a remote overseer board API at URL "
             "(default: $OVERSEER_REMOTE). Runs the verb on the host board.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("--central", help="central state folder (default: derived)")
    p.add_argument("--backup-dir", help="repo-relative or absolute backup dir")
    p.add_argument("--yes", action="store_true",
                    help="accept defaults non-interactively")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("new-card")
    p.add_argument("--title", required=True)
    ref = p.add_mutually_exclusive_group()
    ref.add_argument("--jira")
    ref.add_argument("--linear")
    p.add_argument("--complexity", choices=["S", "M", "L", "XL"])
    p.add_argument("--sprint")
    p.add_argument("--estimate")
    p.add_argument("--goal")
    p.add_argument(
        "--repo",
        help="override the derived top-level repo name (default: derived "
             "from --root via `git rev-parse --git-common-dir`)",
    )
    p.add_argument("--labels", help="comma-separated tags, e.g. policy,architecture")
    p.set_defaults(func=cmd_new_card)

    p = sub.add_parser("set-stage")
    p.add_argument("card_id")
    p.add_argument("stage")
    p.set_defaults(func=cmd_set_stage)

    p = sub.add_parser("block")
    p.add_argument("card_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_block)

    p = sub.add_parser("unblock")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unblock)

    for name, func in (("done", cmd_done), ("abandon", cmd_abandon)):
        p = sub.add_parser(name)
        p.add_argument("card_id")
        p.set_defaults(func=func)

    p = sub.add_parser("set-field")
    p.add_argument("card_id")
    p.add_argument("--branch")
    p.add_argument("--worktree")
    p.add_argument("--pr")
    p.add_argument("--touches")
    p.add_argument("--labels", help="comma-separated tags, e.g. policy,architecture")
    p.add_argument("--parent")
    p.add_argument("--order", type=int)
    p.add_argument("--priority")
    p.add_argument("--repo", help="empty string clears")
    p.add_argument("--title", help="new card title (non-empty)")
    p.add_argument("--body", help="new card body (markdown); empty string clears")
    p.set_defaults(func=cmd_set_field)

    p = sub.add_parser("depends")
    p.add_argument("card_id")
    p.add_argument("--on")
    p.add_argument("--off")
    p.set_defaults(func=cmd_depends)

    p = sub.add_parser("checklist")
    p.add_argument("card_id")
    p.add_argument("--task", required=True)
    p.add_argument("--subject")
    p.add_argument("--status", required=True, choices=CHECKLIST_STATUSES)
    p.set_defaults(func=cmd_checklist)

    sub.add_parser("checklist-sync-hook").set_defaults(func=cmd_checklist_sync_hook)

    p = sub.add_parser("park")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_park)

    p = sub.add_parser("unpark")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unpark)

    p = sub.add_parser("pull-children")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_pull_children)

    p = sub.add_parser("claim")
    p.add_argument("card_id")
    p.add_argument("--session", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("unclaim")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unclaim)

    p = sub.add_parser("claim-nudged")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_claim_nudged)

    sub.add_parser("claim-stop-hook").set_defaults(func=cmd_claim_stop_hook)
    sub.add_parser("claim-prompt-hook").set_defaults(func=cmd_claim_prompt_hook)

    p = sub.add_parser("log-progress")
    p.add_argument("card_id")
    p.add_argument("--note", required=True)
    p.add_argument("--tokens", required=True)
    p.set_defaults(func=cmd_log_progress)

    p = sub.add_parser("log-review")
    p.add_argument("card_id")
    p.add_argument("--stage", required=True)
    p.add_argument("--reviewers", type=int, required=True)
    p.add_argument("--verdict", required=True)
    p.set_defaults(func=cmd_log_review)

    p = sub.add_parser("new-sprint")
    p.add_argument("sprint_id")
    p.add_argument("--estimate")
    p.add_argument("--goal")
    p.set_defaults(func=cmd_new_sprint)

    p = sub.add_parser("rollup-sprint")
    p.add_argument("sprint_id")
    p.set_defaults(func=cmd_rollup_sprint)

    p = sub.add_parser("set-sprint-status")
    p.add_argument("sprint_id")
    p.add_argument("status", choices=sorted(SPRINT_STATUSES))
    p.set_defaults(func=cmd_set_sprint_status)

    sub.add_parser("rebuild-index").set_defaults(func=cmd_rebuild_index)

    p = sub.add_parser("resume")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("conflicts")
    p.add_argument("--sprint")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_conflicts)

    p = sub.add_parser("handoff")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("board")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_board)

    p = sub.add_parser("show")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("repos")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_repos)

    p = sub.add_parser("log-usage")
    p.add_argument("card_id")
    p.add_argument(
        "--role",
        required=True,
        choices=["planner", "worker", "reviewer", "fixer", "orchestrator"],
    )
    p.add_argument("--tokens", required=True)
    p.add_argument("--stage")
    p.add_argument("--tier")
    p.add_argument("--round", type=int)
    p.set_defaults(func=cmd_log_usage)

    p = sub.add_parser("usage")
    p.add_argument("--card")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_usage)

    p = sub.add_parser("calibration")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_calibration)

    p = sub.add_parser("add-fact")
    p.add_argument("--statement", required=True)
    p.add_argument("--tags")
    p.add_argument("--source")
    p.add_argument("--body")
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("verify-fact")
    p.add_argument("fact_id")
    p.set_defaults(func=cmd_verify_fact)

    p = sub.add_parser("retire-fact")
    p.add_argument("fact_id")
    p.add_argument("--superseded-by", dest="superseded_by")
    p.set_defaults(func=cmd_retire_fact)

    p = sub.add_parser("facts")
    p.add_argument("--tag")
    p.add_argument("--stale", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("backup")
    p.add_argument("--dir", help="override the computed backup destination")
    p.add_argument("--print-dir", action="store_true", dest="print_dir",
                    help="print the resolved backup dir and exit without backing up")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore")
    p.add_argument("--dir", help="override the computed backup source")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("clear")
    p.add_argument("--scope", choices=["cards", "repo"], default="repo")
    p.add_argument("--yes", action="store_true",
                   help="skip the interactive confirmation prompt")
    p.add_argument("--no-backup", dest="no_backup", action="store_true",
                   help="do NOT take a recovery snapshot before wiping")
    p.add_argument("--json", action="store_true",
                   help="emit the result as JSON (for the dashboard)")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("label-color")
    label_color_sub = p.add_subparsers(dest="action", required=True)

    lp = label_color_sub.add_parser("set")
    lp.add_argument("name")
    lp.add_argument("color_key", choices=LABEL_PALETTE_KEYS)
    lp.set_defaults(func=cmd_label_color_set)

    lp = label_color_sub.add_parser("clear")
    lp.add_argument("name")
    lp.set_defaults(func=cmd_label_color_clear)

    lp = label_color_sub.add_parser("list")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_label_color_list)

    return parser


def _forwardable_argv(raw_argv: list[str]) -> list[str]:
    """Strip the --remote flag (and its value) from raw argv before forwarding,
    so the host never re-forwards. --root is left for the host to strip/replace
    with its pinned root."""
    out: list[str] = []
    skip = False
    for tok in raw_argv:
        if skip:
            skip = False
            continue
        if tok == "--remote":
            skip = True
            continue
        if tok.startswith("--remote="):
            continue
        out.append(tok)
    return out


def _run_remote(url: str, raw_argv: list[str]) -> int:
    """Forward the whole command to the host board API and relay the result."""
    from scripts import remote  # lazy: httpx only needed on the remote path
    token = os.environ.get("OVERSEER_REMOTE_TOKEN")
    forward = _forwardable_argv(raw_argv)
    stdin = None if sys.stdin.isatty() else sys.stdin.read()
    try:
        res = remote.exec_remote(url, token, forward, stdin)
    except remote.RemoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if res.stdout:
        sys.stdout.write(res.stdout)
    if res.stderr:
        sys.stderr.write(res.stderr)
    return res.returncode


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(raw)
    except SystemExit as exc:  # argparse --help (0) or usage error (2)
        return 0 if not exc.code else 1
    if getattr(args, "remote", None):
        return _run_remote(args.remote, raw)
    try:
        result: int = args.func(args)
        return result
    except (CardParseError, FactParseError, FileNotFoundError, ValueError) as exc:
        # ValueError covers backup.restore_board's designed refusals (no
        # backup found, schema mismatch, corrupt manifest/cards/meta JSON,
        # unknown card column) and config.load_config's malformed-JSON
        # guard — every verb reads config via state_root/central_root, so
        # a broken config.json would otherwise traceback on any command.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        _close_conns()


if __name__ == "__main__":
    raise SystemExit(main())
