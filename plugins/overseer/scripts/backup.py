"""Dump this repo's overseer board to a diffable, committed snapshot, and
restore it back. Git never holds board.db; it holds one JSON file per table
(cards, meta, label colours and -- schema v2 -- sprints, facts, pending facts,
stage evidence) plus ``usage.jsonl``. A v1 snapshot (sprint/knowledge file
trees beside ``cards.json``) still restores, through the importer.

``restore --from-bak`` is the other safety net: it puts back the verified
``board.db.pre-v2.*.bak`` the schema upgrade took, exactly as it was."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts import config, db, views
from scripts.store import derive_repo_label, slugify

IDENTITY_META_KEYS = {
    "repo_root", "schema_version", "workflow_fs_imported", "migrated_from_workflow",
    # board-local upgrade/view bookkeeping: never carried between boards
    "state_imported_v2", "gates_since", "gates_from", "views_exported_at", "v2_report",
}
# "archive/corrupt" is quarantined files ONLY — never "archive/cards", which
# the DB owns and cards.json already carries. migrate_workflow_to_central
# deliberately preserves archive/corrupt/ on disk as unrecoverable-elsewhere
# (see its docstring); excluding it from backup would make that guarantee
# inconsistent, since a lost/rotated central folder would then lose the
# quarantined files backup was supposed to protect.
_COPY_STATE = ("usage.jsonl", "archive/corrupt")
# What a v1 snapshot additionally carried as file trees (restore-only now).
_V1_TREES = ("sprints", "knowledge")


def _dump_table(conn, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def _overseer_version() -> str:
    """Read the plugin's own version from plugin.json, for manifest
    provenance. Never lets a read failure break a backup — falls back to
    an empty string on any error (missing file, malformed JSON, missing key).
    One reader for the manifest: the dashboard's version stamp (WF-053)
    reads it the same way."""
    from scripts.dashboard_record import plugin_version
    return plugin_version()


def _atomic_replace_dir(staged: Path, dest: Path) -> None:
    """Swap ``staged`` into ``dest`` such that ``dest`` or ``dest.old``
    ALWAYS holds a complete snapshot — including across a crash followed by
    a retry. ``backup_dir`` is a repeatedly-refreshed committed path, so the
    overwrite case is the PRIMARY case, not an edge case: the last good
    backup must never be destroyed, no matter where a crash lands.

    On entry, ``old`` (``dest.old``) is disposable stale garbage ONLY when
    ``dest`` also exists — that means a prior swap fully completed. If
    ``dest`` is missing while ``old`` is present, a prior run crashed
    mid-swap (after moving the current snapshot aside, before installing
    the new one); ``old`` IS the recovery snapshot in that case and must be
    restored, never deleted, before proceeding.

    Uses same-filesystem atomic renames (``staged`` is created in
    ``dest.parent`` by the caller) to move the existing snapshot aside,
    swap the new one in, and only then delete the old one — with a
    rollback if the swap itself fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = dest.with_name(dest.name + ".old")
    if old.exists():
        if dest.exists():
            shutil.rmtree(old)  # prior swap completed; old is stale garbage
        else:
            os.replace(old, dest)  # recovery: prior run crashed mid-swap; restore
    if dest.exists():
        os.replace(dest, old)  # atomic rename existing snapshot aside
    try:
        os.replace(staged, dest)  # atomic swap new snapshot in
    except Exception:
        if old.exists() and not dest.exists():
            os.replace(old, dest)  # roll back
        raise
    shutil.rmtree(old, ignore_errors=True)


def _check_dest(dest: Path, repo_root: Path, central: Path) -> None:
    """Refuse a backup destination that ``_atomic_replace_dir`` would clobber
    wholesale: an existing non-empty folder that is not a snapshot of ours (no
    ``manifest.json``), or any ancestor of the repo, the central folder or
    the home directory (OL-1)."""
    resolved = dest.resolve()
    for guarded in (repo_root, central, Path.home()):
        target = guarded.resolve()
        if resolved == target or resolved in target.parents:
            raise ValueError(f"refusing backup destination {dest}: it contains {target}")
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError(f"refusing backup destination {dest}: not a directory")
        if any(resolved.iterdir()) and not (resolved / "manifest.json").is_file():
            raise ValueError(
                f"refusing backup destination {dest}: it is not empty and has no "
                "manifest.json, so it is not an overseer snapshot")


def backup_board(repo_root: Path, dest: Path | None = None) -> dict:
    dest = dest or config.backup_dir(repo_root)
    central = config.central_root(repo_root)
    _check_dest(dest, repo_root, central)
    conn = db.connect(repo_root)
    cards = _dump_table(conn, "cards")
    meta = [m for m in _dump_table(conn, "meta")
            if m["key"] not in IDENTITY_META_KEYS]
    tables = {name: _dump_table(conn, name) for name in db.V2_TABLES}

    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".overseer-bak-", dir=parent))
    try:
        (staged / "cards.json").write_text(json.dumps(cards, indent=2, sort_keys=True))
        (staged / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
        (staged / "label_colors.json").write_text(
            json.dumps(_dump_table(conn, "label_colors"), indent=2, sort_keys=True))
        for name, rows in tables.items():
            (staged / f"{name}.json").write_text(json.dumps(rows, indent=2, sort_keys=True))

        usage_lines = 0
        for name in _COPY_STATE:
            src = central / name
            if src.is_symlink():
                continue
            if src.is_dir():
                shutil.copytree(src, staged / name, symlinks=True)
                for link in [x for x in (staged / name).rglob("*") if x.is_symlink()]:
                    link.unlink()  # never snapshot what a symlink points at
            elif src.is_file():
                shutil.copy2(src, staged / name)
                if name == "usage.jsonl":
                    usage_lines = sum(1 for ln in src.read_text().splitlines() if ln.strip())

        manifest = {
            "schema_version": db.SCHEMA_VERSION,
            "overseer_version": _overseer_version(),
            "created": datetime.now().strftime("%Y-%m-%dT%H:%M"),
            # CLEAN display label, never the (possibly `<label>-<hash>`)
            # central folder name — see config.central_root for why the
            # folder is disambiguated by hash but labels stay clean.
            "repo_label": (
                derive_repo_label(repo_root)
                or slugify(repo_root.resolve().name)
                or "repo"
            ),
            "cards": len(cards),
            # Row counts under the v1 key names (the CLI line and old readers use them).
            "sprint_files": len(tables["sprints"]),
            "fact_files": len(tables["facts"]),
            "pending_facts": len(tables["pending_facts"]),
            "stage_evidence": len(tables["stage_evidence"]),
            "usage_lines": usage_lines,
        }
        (staged / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        _atomic_replace_dir(staged, dest)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return {**{k: manifest[k] for k in ("cards", "sprint_files", "fact_files", "usage_lines")},
            "dest": str(dest)}


def _iso_gt(a: str, b: str) -> bool:
    return (a or "") > (b or "")   # ISO-8601 UTC strings sort lexically


def _load_json_or_raise(path: Path):
    """``json.loads`` a backup file's contents, naming the file in the
    raised ``ValueError`` instead of letting a raw ``JSONDecodeError``
    escape — a corrupt manifest/cards/meta file must fail loudly and
    identifiably, matching ``cards.json``'s existing guard."""
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: corrupt JSON: {exc}") from exc


SUPPORTED_SNAPSHOT_SCHEMAS = (1, 2)


def _restore_table(conn, name: str, rows, src: Path) -> int:
    """Fill-gaps-only restore of one v2 table: a row already on the board is
    never overwritten (``stage_evidence`` rows are matched on their content,
    having only an autoincrement id of their own). Returns rows inserted."""
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError(f"{src / (name + '.json')}: expected a list of row objects")
    known = {r[1] for r in conn.execute(f"PRAGMA table_info({name})").fetchall()}
    inserted = 0
    for row in rows:
        unknown = set(row) - known
        if unknown:
            raise ValueError(f"{src / (name + '.json')}: unknown column(s) {sorted(unknown)}")
        if name == "stage_evidence":
            row = {k: v for k, v in row.items() if k != "id"}
            where = " AND ".join(f'"{k}" IS :{k}' for k in row)
            if conn.execute(f"SELECT 1 FROM stage_evidence WHERE {where}", row).fetchone():
                continue
            verb = "INSERT"
        else:
            verb = "INSERT OR IGNORE"
        cols = ", ".join(f'"{c}"' for c in row)
        ph = ", ".join(f":{c}" for c in row)
        cur = conn.execute(f"{verb} INTO {name} ({cols}) VALUES ({ph})", row)
        inserted += max(0, cur.rowcount)
    return inserted


def restore_board(repo_root: Path, src: Path | None = None) -> dict:
    """Merge a backup snapshot back into the repo's central folder.

    Cards upsert by ``id``, last-modified-wins via ``updated`` (equal
    timestamps keep the current row). Meta merges in, excluding
    ``IDENTITY_META_KEYS``. Sprints, facts, pending facts and stage evidence
    (schema-2 snapshots) and ``usage.jsonl`` fill gaps only -- an existing row
    or file is never overwritten. A schema-1 snapshot's ``sprints/`` and
    ``knowledge/`` trees are copied in (gaps only) and imported the same way.
    Refuses (``ValueError``) on a missing/empty backup dir, an unsupported
    snapshot schema, or corrupt JSON. Refreshes the file views afterwards."""
    src = src or config.backup_dir(repo_root)
    if not src.is_dir() or not (src / "cards.json").exists():
        raise ValueError(f"no backup found at {src}")
    manifest = _load_json_or_raise(src / "manifest.json")
    snapshot_schema = manifest.get("schema_version")
    if snapshot_schema not in SUPPORTED_SNAPSHOT_SCHEMAS:
        raise ValueError(
            f"backup schema {snapshot_schema} is not one of "
            f"{list(SUPPORTED_SNAPSHOT_SCHEMAS)}; refusing to restore")
    rows = _load_json_or_raise(src / "cards.json")

    central = config.central_root(repo_root)
    central.mkdir(parents=True, exist_ok=True)
    conn = db.connect(repo_root)
    known_cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)").fetchall()}
    for row in rows:
        if "id" not in row:
            raise ValueError(f"{src / 'cards.json'}: card row missing required \"id\" field")
        unknown = set(row) - known_cols
        if unknown:
            raise ValueError(
                f"{src / 'cards.json'}: unknown card column(s) {sorted(unknown)}")
    table_rows = {}
    for name in db.V2_TABLES:
        path = src / f"{name}.json"
        if path.exists():
            table_rows[name] = _load_json_or_raise(path)
    inserted = updated = skipped = 0
    with db.txn(conn):
        for row in rows:
            existing = conn.execute(
                "SELECT updated FROM cards WHERE id = ?", (row["id"],)).fetchone()
            if existing is None:
                inserted += 1
            elif _iso_gt(row.get("updated", ""), existing["updated"] or ""):
                updated += 1
            else:
                skipped += 1
                continue
            cols = ", ".join(f'"{c}"' for c in row)
            ph = ", ".join(f":{c}" for c in row)
            upd = ", ".join(f'"{c}" = excluded."{c}"' for c in row if c != "id")
            conn.execute(
                f'INSERT INTO cards ({cols}) VALUES ({ph}) '
                f'ON CONFLICT(id) DO UPDATE SET {upd}', row)
        # meta merge (skip identity keys)
        meta_path = src / "meta.json"
        if meta_path.exists():
            for m in _load_json_or_raise(meta_path):
                if m["key"] in IDENTITY_META_KEYS:
                    continue
                db.set_meta(conn, m["key"], m["value"])
        colors_path = src / "label_colors.json"
        if colors_path.exists():  # absent in older backups
            colors = _load_json_or_raise(colors_path)
            if not isinstance(colors, list) or not all(
                isinstance(c, dict) and isinstance(c.get("name"), str)
                and isinstance(c.get("color_key"), str) for c in colors
            ):
                raise ValueError(
                    f"{colors_path}: expected a list of objects with name and color_key")
            for lc in colors:
                conn.execute(
                    "INSERT OR IGNORE INTO label_colors (name, color_key) VALUES (?, ?)",
                    (lc["name"], lc["color_key"]))
        rows_restored = sum(
            _restore_table(conn, name, table_rows[name], src)
            for name in db.V2_TABLES if name in table_rows)

    files_restored = files_skipped = 0
    for name in (*_COPY_STATE, *(_V1_TREES if snapshot_schema == 1 else ())):
        s = src / name
        if s.is_symlink() or not s.exists():
            continue
        if s.is_dir():
            for f in s.rglob("*"):
                if f.is_symlink() or not f.is_file():
                    continue
                target = central / name / f.relative_to(s)
                if target.exists():
                    files_skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                files_restored += 1
        else:
            target = central / name
            if target.exists():
                files_skipped += 1
            else:
                shutil.copy2(s, target)
                files_restored += 1

    if snapshot_schema == 1:  # file trees -> tables, gaps only
        from scripts import migrate
        with db.txn(conn):
            rows_restored += (lambda r: r.sprints + r.facts + r.retired + r.pending)(
                migrate.import_state(conn, central))
    views.export(conn, central)
    return {"inserted": inserted, "updated": updated, "skipped_older": skipped,
            "files_restored": files_restored, "files_skipped": files_skipped,
            "rows_restored": rows_restored}


def restore_from_bak(repo_root: Path, bak: Path) -> dict:
    """Put a verified ``board.db.pre-v2.*.bak`` back as the live board, exactly
    as it was before the schema upgrade. The board being replaced is first
    saved beside itself as ``<name>.pre-restore.<UTC>.bak``. Close every other
    connection first (the CLI does). Afterwards the board is v1 again: install
    the previous plugin version, or this version will upgrade it again (with a
    fresh backup) on its next use."""
    bak = bak.resolve()
    if not bak.is_file():
        raise ValueError(f"no such backup file: {bak}")
    target = db.board_db_path(repo_root)
    if target.resolve() == bak:
        raise ValueError("refusing to restore a board onto itself")
    probe = sqlite3.connect(f"{bak.as_uri()}?mode=ro", uri=True)
    try:
        try:
            ok = probe.execute("PRAGMA integrity_check").fetchone()[0]
            cards = probe.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"{bak} is not an overseer board backup: {exc}") from exc
        if ok != "ok":
            raise ValueError(f"{bak} failed its integrity check: {ok}")
        safety = None
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safety = target.parent / f"{target.name}.pre-restore.{stamp}.bak"
            live = sqlite3.connect(str(target))
            try:
                out = sqlite3.connect(str(safety))
                try:
                    live.backup(out)
                finally:
                    out.close()
            finally:
                live.close()
        dst = sqlite3.connect(str(target))
        try:
            probe.backup(dst)
        finally:
            dst.close()
    finally:
        probe.close()
    return {"restored_from": str(bak), "cards": cards,
            "previous_board_saved_as": str(safety) if safety else None}
