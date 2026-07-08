import pytest

from scripts.models import Card
from scripts.store import (
    archive_card,
    find_card_path,
    init_workflow,
    load_archived_cards,
    load_live_cards,
    mint_id,
    save_card,
    slugify,
)


def make_card(card_id: str = "WF-001", **overrides: object) -> Card:
    fields = dict(
        id=card_id, title="Fix the thing", status="planned",
        created="2026-07-08", updated="2026-07-08T10:00",
        body="## Goal\nfix it",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


@pytest.fixture
def root(tmp_path):
    return init_workflow(tmp_path)


class TestInit:
    def test_creates_directories(self, tmp_path):
        root = init_workflow(tmp_path)
        for sub in ("cards", "sprints", "archive/cards", "archive/corrupt"):
            assert (root / sub).is_dir()

    def test_gitignore_entry_added_once(self, tmp_path):
        init_workflow(tmp_path)
        init_workflow(tmp_path)
        assert (tmp_path / ".gitignore").read_text().count(".workflow/") == 1

    def test_existing_gitignore_preserved(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        init_workflow(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert "*.pyc" in content and ".workflow/" in content


class TestSlugAndMint:
    def test_slugify(self):
        assert slugify("Fix auth redirect loop on SSO logout!") == (
            "fix-auth-redirect-loop-on-sso-logout"
        )

    def test_mint_first_id(self, root):
        assert mint_id(root) == "WF-001"

    def test_mint_skips_used_and_archived(self, root):
        save_card(root, make_card("WF-004"))
        archive_card(root, make_card("WF-007", status="done"))
        assert mint_id(root) == "WF-008"

    def test_mint_ignores_jira_ids(self, root):
        save_card(root, make_card("PROJ-142"))
        assert mint_id(root) == "WF-001"


class TestSaveLoad:
    def test_save_and_find(self, root):
        save_card(root, make_card())
        path = find_card_path(root, "WF-001")
        assert path.name == "WF-001-fix-the-thing.md"

    def test_find_missing_raises(self, root):
        with pytest.raises(FileNotFoundError):
            find_card_path(root, "WF-999")

    def test_load_live_cards_sorted(self, root):
        save_card(root, make_card("WF-002", title="B"))
        save_card(root, make_card("WF-001", title="A"))
        cards, quarantined = load_live_cards(root)
        assert [c.id for c in cards] == ["WF-001", "WF-002"]
        assert quarantined == []

    def test_corrupt_card_quarantined_not_skipped(self, root):
        save_card(root, make_card())
        bad = root / "cards" / "WF-002-broken.md"
        bad.write_text("no frontmatter at all")
        cards, quarantined = load_live_cards(root)
        assert [c.id for c in cards] == ["WF-001"]
        assert quarantined == [root / "archive" / "corrupt" / "WF-002-broken.md"]
        assert not bad.exists()
        assert quarantined[0].read_text() == "no frontmatter at all"


class TestArchive:
    def test_archive_moves_card(self, root):
        card = make_card()
        save_card(root, card)
        card.complete("2026-07-09T09:00")
        archive_card(root, card)
        assert not (root / "cards" / "WF-001-fix-the-thing.md").exists()
        assert (root / "archive" / "cards" / "WF-001-fix-the-thing.md").exists()

    def test_load_archived_newest_first(self, root):
        older = make_card("WF-001", status="done", updated="2026-07-01T09:00")
        newer = make_card("WF-002", status="done", updated="2026-07-05T09:00")
        archive_card(root, older)
        archive_card(root, newer)
        assert [c.id for c in load_archived_cards(root)] == ["WF-002", "WF-001"]
