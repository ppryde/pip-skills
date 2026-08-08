"""Dump this repo's overseer board to a diffable, committed snapshot, and
restore it back. Git never holds board.db; it holds cards.json + text state."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from scripts import config, db
from scripts.index import rebuild_index

IDENTITY_META_KEYS = {"repo_root", "schema_version", "workflow_fs_imported", "migrated_from_workflow"}
# "archive/corrupt" is quarantined files ONLY — never "archive/cards", which
# the DB owns and cards.json already carries. migrate_workflow_to_central
# deliberately preserves archive/corrupt/ on disk as unrecoverable-elsewhere
# (see its docstring); excluding it from backup would make that guarantee
# inconsistent, since a lost/rotated central folder would then lose the
# quarantined files backup was supposed to protect.
_COPY_STATE = ("sprints", "usage.jsonl", "knowledge", "archive/corrupt")


def _dump_table(conn, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def _overseer_version() -> str:
    """Read the plugin's own version from plugin.json, for manifest
    provenance. Never lets a read failure break a backup — falls back to
    an empty string on any error (missing file, malformed JSON, missing key)."""
    plugin_json = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(plugin_json.read_text())["version"]
    except Exception:
        return ""


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


def backup_board(repo_root: Path, dest: Path | None = None) -> dict:
    dest = dest or config.backup_dir(repo_root)
    central = config.central_root(repo_root)
    conn = db.connect(repo_root)
    cards = _dump_table(conn, "cards")
    meta = [m for m in _dump_table(conn, "meta")
            if m["key"] not in IDENTITY_META_KEYS]

    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".overseer-bak-", dir=parent))
    try:
        (staged / "cards.json").write_text(json.dumps(cards, indent=2, sort_keys=True))
        (staged / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))

        sprint_files = fact_files = usage_lines = 0
        for name in _COPY_STATE:
            src = central / name
            if src.is_dir():
                shutil.copytree(src, staged / name)
                count = sum(1 for _ in (staged / name).rglob("*") if _.is_file())
                if name == "sprints": sprint_files = count
                if name == "knowledge": fact_files = count
            elif src.is_file():
                shutil.copy2(src, staged / name)
                if name == "usage.jsonl":
                    usage_lines = sum(1 for ln in src.read_text().splitlines() if ln.strip())

        manifest = {
            "schema_version": db.SCHEMA_VERSION,
            "overseer_version": _overseer_version(),
            "created": datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "repo_label": central.name,
            "cards": len(cards),
            "sprint_files": sprint_files,
            "fact_files": fact_files,
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


def restore_board(repo_root: Path, src: Path | None = None) -> dict:
    """Merge a backup snapshot back into the repo's central folder.

    Cards upsert by ``id``, last-modified-wins via ``updated`` (equal
    timestamps keep the current row). Meta merges in, excluding
    ``IDENTITY_META_KEYS``. ``sprints/``/``usage.jsonl``/``knowledge/`` fill
    gaps only — an existing file in central is never overwritten. Refuses
    (``ValueError``) on a missing/empty backup dir, a schema mismatch
    against ``db.SCHEMA_VERSION``, or corrupt ``cards.json``. Rebuilds the
    index once the merge is committed.
    """
    src = src or config.backup_dir(repo_root)
    if not src.is_dir() or not (src / "cards.json").exists():
        raise ValueError(f"no backup found at {src}")
    manifest = _load_json_or_raise(src / "manifest.json")
    if manifest.get("schema_version") != db.SCHEMA_VERSION:
        raise ValueError(
            f"backup schema {manifest.get('schema_version')} != current "
            f"{db.SCHEMA_VERSION}; refusing to restore")
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
    inserted = updated = skipped = 0
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
    conn.commit()

    files_restored = files_skipped = 0
    for name in _COPY_STATE:
        s = src / name
        if not s.exists():
            continue
        if s.is_dir():
            for f in s.rglob("*"):
                if not f.is_file():
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

    rebuild_index(repo_root, repo_root.resolve().name, datetime.now().strftime("%Y-%m-%dT%H:%M"))
    return {"inserted": inserted, "updated": updated, "skipped_older": skipped,
            "files_restored": files_restored, "files_skipped": files_skipped}
