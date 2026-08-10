from scripts import db
from scripts.index import rebuild_index
from scripts.store import init_workflow
from factories import make_card

NOW = "2026-07-08T14:32"


def card(card_id: str, **overrides: object):
    overrides.setdefault("title", f"Title {card_id}")
    overrides.setdefault("status", "planned")
    overrides.setdefault("stage", None)
    overrides.setdefault("body", "## Goal\nx")
    return make_card(card_id, **overrides)


class TestRebuildIndex:
    def test_does_not_write_ledger(self, tmp_path):
        root = init_workflow(tmp_path)
        conn = db.connect(tmp_path)
        db.save_card(conn, card("WF-001", status="in-flight", stage="planning"))
        rebuild_index(tmp_path, "proj", NOW)
        assert not (root / "ledger.md").exists()

    def test_returns_quarantined(self, tmp_path):
        init_workflow(tmp_path)
        conn = db.connect(tmp_path)
        db.save_card(conn, card("WF-001", status="in-flight", stage="planning"))
        quarantined = rebuild_index(tmp_path, "proj", NOW)
        # Cards no longer quarantine at this layer -- board.db rows are
        # always structurally valid (see db.load_live_cards's signature).
        # The empty return is still load-bearing: callers (cli.py's
        # _report_quarantined) rely on the shape, and a future db-level
        # corruption check would populate it without an API change.
        assert quarantined == []

    def test_removes_stale_ledger(self, tmp_path):
        root = init_workflow(tmp_path)
        conn = db.connect(tmp_path)
        db.save_card(conn, card("WF-001", status="in-flight", stage="planning"))
        (root / "ledger.md").write_text("stale nonsense")
        rebuild_index(tmp_path, "proj", NOW)
        assert not (root / "ledger.md").exists()
