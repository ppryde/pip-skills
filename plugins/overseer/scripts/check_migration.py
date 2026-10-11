"""Dry-run the schema v2 upgrade against a COPY of a board and report.

    python3 scripts/check_migration.py <board.db> [--state DIR] [--json]

Never writes the board it is given, nor its state folder: it takes a verified
copy of the board (sqlite online backup) and of the legacy ``sprints/`` and
``knowledge/`` trees into a throwaway directory, runs the real upgrade there
(backup, DDL, import, evidence backfill, views, then the upgrade a second time
to prove it idempotent), and prints what happened:

* cards total / live before and after, and whether every card row is identical;
* sprints, facts (live / retired), pending facts imported;
* unparsed files (left in place, listed);
* stage evidence backfilled (rows and cards);
* that a ``.bak`` was taken and verified, and that the second pass changed nothing;
* that the source board and state files were left untouched.

Exit status 0 when the cards survive byte-for-byte and the backup verified.
``--state`` defaults to the folder holding the board.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put the plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import db, migrate, views  # noqa: E402


def _fingerprint(paths: list[Path]) -> dict[str, tuple[int, str]]:
    """(size, sha1) of every file under ``paths`` -- proof the source is untouched."""
    out: dict[str, tuple[int, str]] = {}
    for root in paths:
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            out[str(f)] = (f.stat().st_size, hashlib.sha1(f.read_bytes()).hexdigest())
    return out


def _copy_board(src: Path, dest: Path) -> None:
    """Copy the board file (and any -wal/-shm beside it) with plain file I/O and
    take the online backup from the COPY: the input is never opened through
    sqlite, which would create -wal/-shm files next to it."""
    raw = dest.with_name("source-copy.db")
    shutil.copyfile(src, raw)
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.is_file():
            shutil.copyfile(side, raw.with_name(raw.name + suffix))
    source = sqlite3.connect(str(raw))
    try:
        out = sqlite3.connect(str(dest))
        try:
            source.backup(out)
        finally:
            out.close()
    finally:
        source.close()
    for stale in raw.parent.glob(raw.name + "*"):
        stale.unlink(missing_ok=True)


def _card_columns(path: Path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(cards)")]
    finally:
        conn.close()


def _card_rows(path: Path, cols: list[str]) -> list[tuple]:
    """Every card row over the ORIGINAL columns (an upgrade may add columns)."""
    conn = sqlite3.connect(str(path))
    try:
        order = ", ".join(f'"{c}"' for c in cols)
        return conn.execute(f"SELECT {order} FROM cards ORDER BY id").fetchall()
    finally:
        conn.close()


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    one = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
    return {
        "cards_total": one("SELECT COUNT(*) FROM cards"),
        "cards_live": one("SELECT COUNT(*) FROM cards WHERE archived = 0"),
        "sprints": one("SELECT COUNT(*) FROM sprints"),
        "facts_live": one("SELECT COUNT(*) FROM facts WHERE retired = 0"),
        "facts_retired": one("SELECT COUNT(*) FROM facts WHERE retired = 1"),
        "pending": one("SELECT COUNT(*) FROM pending_facts"),
        "evidence_rows": one("SELECT COUNT(*) FROM stage_evidence"),
        "evidence_cards": one("SELECT COUNT(DISTINCT card_id) FROM stage_evidence"),
    }


def check(board: Path, state: Path) -> dict:
    sides = [board.with_name(board.name + s) for s in ("-wal", "-shm")]
    watched = [board, *(p for p in sides if p.exists()),
               *(p for p in (state / "sprints", state / "knowledge") if p.exists())]
    before = _fingerprint(watched)
    present = {p for p in sides if p.exists()}

    with tempfile.TemporaryDirectory(prefix="overseer-check-") as tmp_name:
        tmp = Path(tmp_name)
        probe = tmp / "probe.db"
        _copy_board(board, probe)
        src = sqlite3.connect(str(probe))
        try:
            user_version = src.execute("PRAGMA user_version").fetchone()[0]
            src_total = src.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            src_live = src.execute("SELECT COUNT(*) FROM cards WHERE archived = 0").fetchone()[0]
        finally:
            src.close()
        probe.unlink()
        copy_state = tmp / "state"
        copy_state.mkdir()
        for sub in ("sprints", "knowledge"):
            if (state / sub).is_dir():
                shutil.copytree(state / sub, copy_state / sub, symlinks=True)
        copy_db = tmp / "board.db"
        _copy_board(board, copy_db)
        columns = _card_columns(copy_db)
        original_rows = _card_rows(copy_db, columns)

        conn = sqlite3.connect(str(copy_db))
        conn.row_factory = sqlite3.Row
        report: dict = {}
        try:
            db.ensure_schema(conn, path=copy_db, state=copy_state)
            meta = json.loads(db.get_meta(conn, "v2_report") or "{}")
            conn.execute("DELETE FROM meta WHERE key = 'v2_report'")
            conn.commit()
            views_ok = views.export(conn, copy_state)
            counts = _counts(conn)
            baks = sorted(tmp.glob("board.db.pre-v2.*.bak"))
            bak_ok = False
            if baks:
                check_conn = sqlite3.connect(str(baks[-1]))
                try:
                    bak_ok = (check_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                              and check_conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
                              == src_total)
                finally:
                    check_conn.close()
            # Idempotence: the same import again finds nothing new.
            with db.txn(conn):
                again = migrate.import_state(conn, copy_state)
            second = {"sprints": again.sprints, "facts": again.facts + again.retired,
                      "pending": again.pending}
            cards_identical = _card_rows(copy_db, columns) == original_rows
            report = {
                "board": str(board),
                "state": str(state),
                "schema_before": user_version,
                "cards_before": {"total": src_total, "live": src_live},
                "after": counts,
                "cards_identical": cards_identical,
                "unparsed": meta.get("unparsed", []),
                "bak_verified": bak_ok,
                "views_written": views_ok,
                "second_import_new_rows": second,
                "idempotent": not any(second.values()),
            }
        finally:
            conn.close()
    report["already_v2"] = user_version >= db.SCHEMA_VERSION
    if report["already_v2"]:
        report["bak_verified"] = True  # nothing to upgrade, so no backup is expected
    report["source_untouched"] = (
        _fingerprint(watched) == before
        and present == {p for p in sides if p.exists()}
    )
    return report


def render(r: dict) -> str:
    a = r["after"]
    lines = [
        *(["board is already at schema v2: nothing to upgrade"] if r.get("already_v2") else []),
        f"board:   {r['board']}",
        f"state:   {r['state']}",
        f"schema before: user_version {r['schema_before']}",
        f"cards before:  {r['cards_before']['total']} total / {r['cards_before']['live']} live",
        f"cards after:   {a['cards_total']} total / {a['cards_live']} live "
        f"(rows identical: {'yes' if r['cards_identical'] else 'NO'})",
        f"sprints: {a['sprints']}",
        f"facts:   {a['facts_live']} live / {a['facts_retired']} retired",
        f"pending: {a['pending']}",
        f"evidence backfilled: {a['evidence_rows']} rows across {a['evidence_cards']} cards",
        f"unparsed files: {len(r['unparsed'])}",
        *[f"  - {u}" for u in r["unparsed"]],
        f".bak taken and verified: {'n/a (already v2)' if r.get('already_v2') else 'yes' if r['bak_verified'] else 'NO'}",
        f"views written: {'yes' if r['views_written'] else 'NO'}",
        f"second pass imported new rows: {r['second_import_new_rows']} "
        f"(idempotent: {'yes' if r['idempotent'] else 'NO'})",
        f"source board and state untouched: {'yes' if r['source_untouched'] else 'NO'}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("board", type=Path, help="path to a board.db (it is only read)")
    parser.add_argument("--state", type=Path, help="folder holding sprints/ and knowledge/ "
                        "(default: the board's folder)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    board = args.board.expanduser()
    if not board.is_file():
        print(f"error: no such board: {board}", file=sys.stderr)
        return 1
    state = (args.state or board.parent).expanduser()
    report = check(board, state)
    print(json.dumps(report, indent=2) if args.json else render(report))
    ok = (report["cards_identical"] and report["bak_verified"] and report["idempotent"]
          and report["source_untouched"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
