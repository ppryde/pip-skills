"""Ledger retirement (WF-072). ``ledger.md`` was a gitignored, write-only
view regenerated on every mutation that nothing read (board.db is the
source of truth; the CLI, dashboard, and resume all read it directly). This
module no longer generates that file. What remains: surfacing quarantined
(corrupt) cards on rebuild, and removing any stale ``ledger.md`` left over
from before the retirement."""
from __future__ import annotations

from pathlib import Path

from scripts import db
from scripts.store import state_root


def rebuild_index(repo_root: Path, project: str, now: str) -> list[Path]:
    """Reconcile card state: surface quarantined (corrupt) cards and remove
    any stale ``ledger.md`` left over from before the file was retired
    (WF-072). No longer writes a ledger — board.db is the source of truth
    and nothing reads ``ledger.md``. ``project`` and ``now`` are unused but
    kept in the signature to avoid rippling changes through the 9 call
    sites and the public ``rebuild-index`` CLI verb."""
    root = state_root(repo_root)
    conn = db.connect(repo_root)
    _cards, quarantined = db.load_live_cards(conn)
    (root / "ledger.md").unlink(missing_ok=True)
    return quarantined
