"""scripts/check_migration.py: the dry run attached to the PR."""
import json
import subprocess
import sys
from pathlib import Path

from test_migration import card_rows, make_v1_board

SCRIPT = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "scripts" / "check_migration.py"


def test_dry_run_reports_and_writes_nothing(tmp_path):
    board, state = tmp_path / "board.db", tmp_path / "state"
    make_v1_board(board, state)
    before = (board.read_bytes(), card_rows(board), sorted(p.name for p in tmp_path.iterdir()))
    proc = subprocess.run([sys.executable, str(SCRIPT), str(board), "--state", str(state), "--json"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert r["cards_before"] == {"total": 260, "live": 174}
    assert r["after"]["cards_total"] == 260 and r["cards_identical"]
    assert (r["after"]["sprints"], r["after"]["facts_live"], r["after"]["facts_retired"],
            r["after"]["pending"]) == (2, 3, 1, 2)
    assert len(r["unparsed"]) == 3
    assert r["after"]["evidence_rows"] == 4 and r["after"]["evidence_cards"] == 1
    assert r["bak_verified"] and r["idempotent"] and r["source_untouched"]
    # the board it was given, its folder and its state are exactly as they were
    assert (board.read_bytes(), card_rows(board), sorted(p.name for p in tmp_path.iterdir())) == before


def test_text_report_names_every_figure(tmp_path):
    board, state = tmp_path / "board.db", tmp_path / "state"
    make_v1_board(board, state, n_cards=9)
    out = subprocess.run([sys.executable, str(SCRIPT), str(board), "--state", str(state)],
                         capture_output=True, text=True).stdout
    for needle in ("cards before:  9 total", "sprints: 2", "facts:   3 live / 1 retired",
                   "pending: 2", "evidence backfilled", "unparsed files: 3", ".bak taken and verified: yes"):
        assert needle in out


def test_missing_board_is_an_error(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.db")],
                          capture_output=True, text=True)
    assert proc.returncode == 1 and "no such board" in proc.stderr


def test_wal_side_files_are_not_created_beside_the_input(tmp_path):
    import sqlite3
    board, state = tmp_path / "board.db", tmp_path / "state"
    make_v1_board(board, state, n_cards=5)
    for side in tmp_path.glob("board.db-*"):
        side.unlink()
    proc = subprocess.run([sys.executable, str(SCRIPT), str(board), "--state", str(state), "--json"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert sorted(p.name for p in tmp_path.glob("board.db-*")) == []
    assert json.loads(proc.stdout)["source_untouched"]


def test_an_already_upgraded_board_is_reported_not_failed(tmp_path):
    from scripts import db
    import sqlite3
    board, state = tmp_path / "board.db", tmp_path / "state"
    make_v1_board(board, state, n_cards=3)
    conn = sqlite3.connect(str(board))
    conn.row_factory = sqlite3.Row
    db.ensure_schema(conn, path=board, state=state)
    conn.close()
    proc = subprocess.run([sys.executable, str(SCRIPT), str(board), "--state", str(state)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "already at schema v2" in proc.stdout
