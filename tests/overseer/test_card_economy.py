import threading

from factories import db_repo, make_card

from scripts import db


class TestRecordReview:
    def test_parallel_reviewers_share_one_round_header(self):
        card = make_card("WF-001")
        card.record_review("impl-review", 1, "A", "found wanting 1C 0I 0M → /d/r1-A.md", "t1")
        card.record_review("impl-review", 1, "B", "approved 0C 0I 1M → /d/r1-B.md", "t2")
        card.record_review("impl-review", 2, "A", "approved 0C 0I 0M → /d/r2-A.md", "t3")
        log = card.sections["## Review log"]
        assert log == (
            "### impl-review — round 1\n"
            "- A: found wanting 1C 0I 0M → /d/r1-A.md\n"
            "- B: approved 0C 0I 1M → /d/r1-B.md\n"
            "### impl-review — round 2\n"
            "- A: approved 0C 0I 0M → /d/r2-A.md"
        )
        assert card.review_rounds("impl-review") == 2
        assert card.updated == "t3"

    def test_round_1_header_does_not_match_round_10(self):
        card = make_card("WF-001")
        card.record_review("impl-review", 10, "A", "approved 0C 0I 0M → /d/r10-A.md", "t")
        card.record_review("impl-review", 1, "A", "approved 0C 0I 0M → /d/r1-A.md", "t")
        assert card.review_rounds("impl-review") == 2

    def test_joins_legacy_header_with_reviewer_count(self):
        card = make_card("WF-001")
        card.log_review("plan-review", 2, "legacy verdict", "t")
        card.record_review("plan-review", 1, "B", "approved 0C 0I 0M → /d/r1-B.md", "t")
        assert card.review_rounds("plan-review") == 1
        assert "- B: approved" in card.sections["## Review log"]


class TestSetSection:
    def test_replaces_existing_and_demotes_headers(self):
        card = make_card("WF-001", body="## Goal\ng\n\n## Plan\n_(pending)_\n\n## Decisions\nd")
        card.set_section("## Plan", "# Title\n## Chunks\n1. do it\n", "t")
        assert card.sections["## Plan"] == "### Title\n### Chunks\n1. do it"
        assert card.sections["## Decisions"] == "d"
        assert list(card.sections) == ["## Goal", "## Plan", "## Decisions"]

    def test_appends_missing_section(self):
        card = make_card("WF-001", body="## Goal\ng")
        card.set_section("## Verification", "all green", "t")
        assert card.sections["## Verification"] == "all green"


class TestOrchestrators:
    def test_stamp_clear_and_filter(self, tmp_path, monkeypatch):
        _, conn = db_repo(tmp_path, monkeypatch)
        for cid, status, archived in [("WF-001", "in-flight", False),
                                      ("WF-002", "parked", False),
                                      ("WF-003", "blocked", False),
                                      ("WF-004", "done", True)]:
            card = make_card(cid, status=status)
            (db.archive_card if archived else db.save_card)(conn, card)
            db.stamp_orchestrator(conn, cid, "sess-1", "t")
        db.stamp_orchestrator(conn, "WF-001", "sess-2", "t2")  # re-stamp moves it
        assert [c.id for c in db.orchestrated_cards(conn, "sess-1")] == ["WF-003"]
        assert [c.id for c in db.orchestrated_cards(conn, "sess-2")] == ["WF-001"]
        db.clear_orchestrator(conn, "WF-003")
        assert db.orchestrated_cards(conn, "sess-1") == []


class TestMutateCard:
    def test_missing_card_returns_none(self, tmp_path, monkeypatch):
        _, conn = db_repo(tmp_path, monkeypatch)
        assert db.mutate_card(conn, "WF-404", lambda c: None) is None

    def test_concurrent_mutations_both_land(self, tmp_path, monkeypatch):
        repo, conn = db_repo(tmp_path, monkeypatch)
        db.save_card(conn, make_card("WF-001"))
        barrier = threading.Barrier(8)

        def worker(slot: str) -> None:
            own = db.connect(repo, migrate=False)
            barrier.wait()
            db.mutate_card(own, "WF-001", lambda c: c.record_review(
                "impl-review", 1, slot, f"approved 0C 0I 0M → /d/r1-{slot}.md", "t"))
            own.close()

        threads = [threading.Thread(target=worker, args=(s,)) for s in "ABCDEFGH"]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log = db.load_card(conn, "WF-001").sections["## Review log"]
        assert all(f"- {s}: approved" in log for s in "ABCDEFGH")
