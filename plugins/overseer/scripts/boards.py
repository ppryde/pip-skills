"""Find and merge the several boards one repo can end up with.

A repo should have ONE board. It ends up with more when a second Claude
account (its own config dir) raised its own, or when the legacy plain
``overseer/<label>/`` folder and the hashed ``<label>-<hash>/`` one both exist.
Once the extra config dirs are watched (``config.claude_dirs``) the repo
RESOLVES to one folder again — but the cards that landed in the others are
stranded. ``merge_boards`` folds them into the resolved board:

- cards unioned by id; where both have a card, the more recently ``updated``
  copy wins (ISO strings compare lexically) — the archived flag rides along;
- label colours unioned (the target's win on a clash);
- ``knowledge/`` and ``usage.jsonl`` MOVE to the target when the target has
  none of its own (the common case: an empty board that won the lookup);
  when both sides have one, the source's stays where it is. Schema v2 keeps
  facts in board.db, so a moved ``knowledge/`` is imported into the target's
  tables (never overwriting) and the views refreshed; sprints a v2 source holds
  are added by id (the target's win);
- each absorbed folder is RENAMED ``<name>.absorbed-<stamp>``, never deleted,
  so anything left behind is a folder rename away.

Idempotent in effect: a second run finds nothing to absorb.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from scripts import config, db, knowledge, migrate, views
from scripts.store import derive_repo_label, derive_repo_root, slugify

# Per-board files beside board.db worth carrying across when the target has
# none of its own.
SIDECARS = ("knowledge", "usage.jsonl")


def _read_only(path: Path) -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
    except (sqlite3.Error, ValueError):
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _describe(folder: Path, active: Path) -> dict[str, Any] | None:
    board = folder / "board.db"
    conn = _read_only(board)
    if conn is None:
        return None
    try:
        try:
            cards, updated = conn.execute("SELECT COUNT(*), MAX(updated) FROM cards").fetchone()
        except sqlite3.Error:
            return None
        return {
            "path": str(folder),
            "cards": int(cards),
            "updated": updated,
            "active": folder.resolve() == active.resolve(),
            "knowledge": (folder / "knowledge").is_dir(),
            "usage": (folder / "usage.jsonl").is_file(),
        }
    finally:
        conn.close()


def find_boards(repo_root: Path) -> list[dict[str, Any]]:
    """Every board folder for ``repo_root`` across the watched config dirs —
    the hashed and the legacy plain name under each — that has a board.db
    owned by this repo. The resolved (``active``) one is listed first."""
    canonical = derive_repo_root(repo_root) or repo_root
    label = derive_repo_label(repo_root) or slugify(repo_root.resolve().name) or "repo"
    active = config.central_root(repo_root)
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    candidates = [active]
    for config_dir in config.claude_dirs():
        base = config_dir / "overseer"
        candidates.append(base / f"{label}-{config._short_hash(canonical)}")
        candidates.append(base / label)
    for folder in candidates:
        try:
            key = folder.resolve()
        except OSError:
            continue
        if key in seen or not (folder / "board.db").is_file():
            continue
        seen.add(key)
        if folder != active and not config._owns_plain(folder, canonical):
            continue  # a same-named folder that positively belongs to another repo
        entry = _describe(folder, active)
        if entry is not None:
            found.append(entry)
    found.sort(key=lambda e: (not e["active"], e["path"]))
    return found


def _open_target(folder: Path, repo_root: Path, *, write: bool) -> sqlite3.Connection:
    """The resolved board, by path. `write=True` opens it exactly as the
    board's own sessions do (`db.connect_at`: WAL, busy timeout, foreign keys,
    schema, the repo-identity stamp), creating it if need be. `write=False`
    never creates it: a missing target reads as an empty board (an in-memory
    schema) so a dry run stays a dry run."""
    board = folder / "board.db"
    if write:
        return db.connect_at(board, repo_root)
    if board.is_file():
        conn = _read_only(board)
        if conn is not None:
            return conn
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.ensure_schema(conn)
    return conn


class _LenientRow(dict):
    """A card row from an OLDER board, read as ``row[column]`` by
    ``db.row_to_card``: a column the old schema never had reads as None
    (which every field there treats as its default) instead of raising."""

    def __missing__(self, key: str) -> None:
        return None


def _card_index(target: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """``id -> (updated, created)`` for every card the target holds."""
    return {
        row["id"]: (row["updated"] or "", row["created"] or "")
        for row in target.execute("SELECT id, updated, created FROM cards")
    }


def _merge_cards(target: sqlite3.Connection, source: sqlite3.Connection,
                 existing: dict[str, tuple[str, str]], *, apply: bool = True) -> dict[str, Any]:
    """Union `source`'s cards into `target` — a missing card is added, a
    shared one is replaced only when the source copy is newer. ``existing``
    is the target's card index (``_card_index``), kept current as cards land
    so it can be shared across every absorbed board of one run. With
    ``apply=False`` (dry run) the same comparison is made and counted but
    nothing is written — the index still advances, so a card two absorbed
    boards both hold previews as one add and one compare, exactly as the
    real merge would land it.

    Two boards minted independently both start at WF-001, so a shared id is
    only the same card when its ``created`` stamp matches too. A shared id
    with a different ``created`` is a COLLISION: two unrelated cards. The
    target's is kept, the source's is left in the absorbed folder, and the
    id is reported in ``conflicts`` for a person to resolve — the merge never
    overwrites one task with another on the strength of a timestamp."""
    added = updated = kept = 0
    conflicts: list[str] = []
    for row in source.execute("SELECT * FROM cards"):
        lenient = _LenientRow(dict(row))
        card = db.row_to_card(lenient)  # type: ignore[arg-type]
        archived = int(lenient["archived"] or 0)
        if card.id not in existing:
            added += 1
        else:
            t_updated, t_created = existing[card.id]
            if (card.created or "") != t_created:
                conflicts.append(card.id)
                continue
            if (card.updated or "") > t_updated:
                updated += 1
            else:
                kept += 1
                continue
        existing[card.id] = (card.updated or "", card.created or "")
        if apply:
            db._upsert(target, card, archived, commit=False)
    return {"added": added, "updated": updated, "kept": kept, "conflicts": conflicts}


def _merge_label_colors(target: sqlite3.Connection, source: sqlite3.Connection) -> int:
    n = 0
    try:
        rows = source.execute("SELECT name, color_key FROM label_colors").fetchall()
    except sqlite3.OperationalError:
        return 0  # a board from before label colours existed
    for row in rows:
        cur = target.execute(
            "INSERT OR IGNORE INTO label_colors(name, color_key) VALUES (?, ?)",
            (row["name"], row["color_key"]),
        )
        n += max(0, cur.rowcount)
    return n


def _merge_sprints(target: sqlite3.Connection, folder: Path) -> int:
    """Add the sprints a schema-v2 source board holds that the target lacks."""
    source = _read_only(folder / "board.db")
    if source is None:
        return 0
    try:
        try:
            rows = source.execute("SELECT * FROM sprints").fetchall()
        except sqlite3.OperationalError:
            return 0  # a v1 source: its sprint files stay in the absorbed folder
        added = 0
        with db.txn(target):
            for r in rows:
                cur = target.execute(
                    "INSERT OR IGNORE INTO sprints(id, status, budget_estimate, budget_actual, "
                    "started, body, updated) VALUES (?,?,?,?,?,?,?)",
                    (r["id"], r["status"], r["budget_estimate"], r["budget_actual"],
                     r["started"], r["body"], r["updated"]))
                added += max(0, cur.rowcount)
        return added
    finally:
        source.close()


def _merge_knowledge_rows(target: sqlite3.Connection, folder: Path) -> tuple[int, list[dict[str, str]]]:
    """Add the facts and pending facts a schema-v2 source board holds that the
    target lacks. A fact whose id the target already holds with the SAME
    statement is the same fact (skipped); with a DIFFERENT statement it is a
    different fact that merely shares a per-board ``KB-nnn``, so it is re-minted
    under the next free id (``superseded_by`` links follow). Returns the count
    added and the ``[{"from", "to"}]`` re-mints."""
    source = _read_only(folder / "board.db")
    if source is None:
        return 0, []
    try:
        try:
            facts = source.execute("SELECT * FROM facts").fetchall()
            pending = source.execute("SELECT * FROM pending_facts").fetchall()
        except sqlite3.OperationalError:
            return 0, []  # a v1 source: its knowledge/ files are imported instead
        added = 0
        remints: list[dict[str, str]] = []
        with db.txn(target):
            mapping: dict[str, str] = {}
            inserted: set[str] = set()
            for r in facts:
                held = target.execute("SELECT statement FROM facts WHERE id = ?", (r["id"],)).fetchone()
                if held is not None and held["statement"] != r["statement"]:
                    mapping[r["id"]] = knowledge.mint_fact_id(target)
                    remints.append({"from": r["id"], "to": mapping[r["id"]]})
                    _insert_fact(target, r, mapping)
                    added += 1
                    inserted.add(r["id"])
                else:
                    if _insert_fact(target, r, mapping) > 0:
                        added += 1
                        inserted.add(r["id"])
            for r in facts:  # supersession links follow a re-mint wherever it fell in the order
                if r["id"] in inserted and r["superseded_by"] in mapping:
                    target.execute("UPDATE facts SET superseded_by = ? WHERE id = ?",
                                   (mapping[r["superseded_by"]], mapping.get(r["id"], r["id"])))
            for r in pending:
                cols = r.keys()
                cur = target.execute(
                    f"INSERT OR IGNORE INTO pending_facts({', '.join(chr(34) + c + chr(34) for c in cols)}) "
                    f"VALUES ({', '.join('?' for _ in cols)})", tuple(r))
                added += max(0, cur.rowcount)
        return added, remints
    finally:
        source.close()


def _insert_fact(target: sqlite3.Connection, r: sqlite3.Row, mapping: dict[str, str]) -> int:
    values = {c: r[c] for c in r.keys()}
    values["id"] = mapping.get(r["id"], r["id"])
    cols = list(values)
    cur = target.execute(
        f"INSERT OR IGNORE INTO facts({', '.join(chr(34) + c + chr(34) for c in cols)}) "
        f"VALUES ({', '.join('?' for _ in cols)})", tuple(values[c] for c in cols))
    return cur.rowcount


def merge_boards(repo_root: Path, *, dry_run: bool = False,
                 now: float | None = None) -> dict[str, Any]:
    """Fold every other board for ``repo_root`` into the resolved one (see
    module docstring). Returns the plan/result: the target, and per absorbed
    folder the card counts and where it was renamed to."""
    boards = find_boards(repo_root)
    target = next((b for b in boards if b["active"]), None)
    others = [b for b in boards if not b["active"]]
    result: dict[str, Any] = {
        "target": target["path"] if target else str(config.central_root(repo_root)),
        "dry_run": dry_run,
        "absorbed": [],
    }
    if not others:
        return result
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
    # The target is opened BY PATH — the folder `find_boards` resolved — never
    # via `db.connect(repo_root)`, which honours the OVERSEER_DB file override
    # and could point somewhere else. A dry run reads it (or, if it does not
    # exist yet, an empty in-memory stand-in) and creates nothing; the real
    # merge creates/migrates it.
    target_conn = _open_target(Path(result["target"]), repo_root, write=not dry_run)
    try:
        existing = _card_index(target_conn)
        for other in others:
            folder = Path(other["path"])
            source = _read_only(folder / "board.db")
            if source is None:
                continue
            try:
                stats = _merge_cards(target_conn, source, existing, apply=not dry_run)
                colours = 0 if dry_run else _merge_label_colors(target_conn, source)
                if not dry_run:
                    target_conn.commit()
            finally:
                source.close()
            target_folder = Path(result["target"])
            sprints_added = 0 if dry_run else _merge_sprints(target_conn, folder)
            facts_added, remints = (0, []) if dry_run else _merge_knowledge_rows(target_conn, folder)
            moved: list[str] = []
            left_behind: list[str] = []
            for name in SIDECARS:
                src, dst = folder / name, target_folder / name
                if not src.exists():
                    continue
                if dst.exists():
                    if name == "knowledge" and not dry_run:
                        # The target already has a knowledge/ (views): take the
                        # source's legacy fact files into the tables by id.
                        with db.txn(target_conn):
                            report = migrate.import_state(target_conn, folder)
                        facts_added += report.facts + report.retired + report.pending
                        continue
                    left_behind.append(name)
                    continue
                moved.append(name)
                if not dry_run:
                    shutil.move(str(src), str(dst))
            if moved and not dry_run:
                with db.txn(target_conn):
                    migrate.import_state(target_conn, target_folder)
            renamed = folder.with_name(f"{folder.name}.absorbed-{stamp}")
            watch_config = None
            if not dry_run:
                # Watching becomes mutual — written BEFORE the rename so a
                # failure leaves the folder in place: the account the folder
                # lived under must resolve to the merged board, not an empty one.
                if folder.parent.name == target_folder.parent.name == "overseer":
                    written = config.watch_from(folder.parent.parent, target_folder.parent.parent)
                    watch_config = str(written) if written else None
                folder.rename(renamed)
            result["absorbed"].append({
                "from": str(folder),
                "renamed_to": str(renamed),
                "watch_config": watch_config,
                **stats,
                "label_colors": colours,
                "sprints": sprints_added,
                "facts": facts_added,
                "facts_reminted": remints,
                "moved": moved,
                "left_behind": left_behind,
            })
        if not dry_run and result["absorbed"]:
            views.export(target_conn, Path(result["target"]))
    finally:
        target_conn.close()
    return result
