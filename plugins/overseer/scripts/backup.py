"""Dump this repo's overseer board to a diffable, committed snapshot, and
restore it back. Git never holds board.db; it holds cards.json + text state."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from scripts import config, db

SCHEMA_TABLES = ("cards", "meta")
IDENTITY_META_KEYS = {"repo_root", "schema_version", "workflow_fs_imported", "migrated_from_workflow"}
_COPY_STATE = ("sprints", "usage.jsonl", "knowledge")


def _dump_table(conn, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def _atomic_replace_dir(staged: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(staged), str(dest))


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
        "repo_label": central.name,
        "cards": len(cards),
        "sprint_files": sprint_files,
        "fact_files": fact_files,
        "usage_lines": usage_lines,
    }
    (staged / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    _atomic_replace_dir(staged, dest)
    return {**{k: manifest[k] for k in ("cards", "sprint_files", "fact_files", "usage_lines")},
            "dest": str(dest)}
