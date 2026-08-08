import subprocess

import pytest

from scripts.models import Card
from scripts.store import (
    archive_card,
    derive_repo_label,
    derive_repo_root,
    find_card_path,
    init_workflow,
    load_archived_cards,
    load_live_cards,
    mint_id,
    save_card,
    slugify,
    state_root,
)
from tests.factories import git_init as _git_init


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

    def test_gitignore_entry_added_once(self, tmp_path, monkeypatch):
        # init_workflow only touches .gitignore when the resolved state root
        # is the repo-local .workflow/ dir — under central storage that's no
        # longer the default, so force it via OVERSEER_CENTRAL to exercise
        # the branch directly.
        monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / ".workflow"))
        init_workflow(tmp_path)
        init_workflow(tmp_path)
        assert (tmp_path / ".gitignore").read_text().count(".workflow/") == 1

    def test_existing_gitignore_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / ".workflow"))
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

    def test_quarantine_collision_does_not_overwrite(self, root):
        bad = root / "cards" / "WF-002-broken.md"
        bad.write_text("first corruption")
        load_live_cards(root)
        bad.write_text("second corruption")
        _, quarantined = load_live_cards(root)
        corrupt_dir = root / "archive" / "corrupt"
        assert (corrupt_dir / "WF-002-broken.md").read_text() == "first corruption"
        assert quarantined == [corrupt_dir / "WF-002-broken.1.md"]
        assert quarantined[0].read_text() == "second corruption"
        assert len(list(corrupt_dir.glob("*.md"))) == 2


class TestArchive:
    def test_archive_moves_card(self, root):
        card = make_card()
        save_card(root, card)
        card.complete("2026-07-09T09:00")
        archive_card(root, card)
        assert not (root / "cards" / "WF-001-fix-the-thing.md").exists()
        assert (root / "archive" / "cards" / "WF-001-fix-the-thing.md").exists()

    def test_archive_collision_uniquifies_and_preserves_first(self, root):
        first = make_card("WF-005", title="Same title", body="## Goal\nfirst body")
        archive_card(root, first)
        second = make_card("WF-005", title="Same title", body="## Goal\nsecond body")
        target = archive_card(root, second)
        archive_dir = root / "archive" / "cards"
        assert (archive_dir / "WF-005-same-title.md").exists()
        assert target == archive_dir / "WF-005-same-title.1.md"
        assert target.exists()
        assert "first body" in (archive_dir / "WF-005-same-title.md").read_text()
        assert "second body" in target.read_text()

    def test_load_archived_newest_first(self, root):
        older = make_card("WF-001", status="done", updated="2026-07-01T09:00")
        newer = make_card("WF-002", status="done", updated="2026-07-05T09:00")
        archive_card(root, older)
        archive_card(root, newer)
        assert [c.id for c in load_archived_cards(root)] == ["WF-002", "WF-001"]


class TestStateRoot:
    """``state_root`` is now a thin delegate to ``config.central_root`` (see
    ``TestStateRootDelegatesToConfig`` below); the old ``.workflow/`` vs
    gitignored-``scratch/`` precedence logic it used to implement itself was
    removed in the central-storage migration, so those scenarios no longer
    apply here — they're covered as ``config.central_root`` precedence in
    ``tests/test_config.py`` instead."""

    def test_default_resolves_under_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        cfgdir = tmp_path / "cfg"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
        _git_init(tmp_path)
        assert state_root(tmp_path) == cfgdir / "overseer" / tmp_path.name

    def test_env_override_wins(self, tmp_path, monkeypatch):
        central = tmp_path / "central-elsewhere"
        monkeypatch.setenv("OVERSEER_CENTRAL", str(central))
        assert state_root(tmp_path) == central

    def test_init_under_central_root_skips_gitignore_edit(self, tmp_path, monkeypatch):
        central = tmp_path / "central-elsewhere"
        monkeypatch.setenv("OVERSEER_CENTRAL", str(central))
        root = init_workflow(tmp_path)
        assert root == central
        assert (root / "cards").is_dir()
        assert not (tmp_path / ".gitignore").exists()


class TestDeriveRepoLabel:
    def test_main_repo_uses_top_level_name(self, tmp_path):
        main_repo = tmp_path / "pip-skills"
        main_repo.mkdir()
        _git_init(main_repo)
        assert derive_repo_label(main_repo) == "pip-skills"

    def test_worktree_derives_main_repo_name_not_worktree_dirname(self, tmp_path):
        """A ledger root living inside a linked worktree (e.g.
        `.claude/worktrees/overseer-orchestration`) must still record the
        MAIN repo's name — never the worktree directory's own basename."""
        main_repo = tmp_path / "pip-skills"
        main_repo.mkdir()
        _git_init(main_repo)
        (main_repo / "README.md").write_text("x")
        subprocess.run(["git", "add", "."], cwd=main_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=main_repo, check=True,
            capture_output=True,
        )
        subprocess.run(["git", "branch", "wt-branch"], cwd=main_repo, check=True)

        worktree_dir = tmp_path / "totally-unrelated-worktree-name"
        subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "wt-branch"],
            cwd=main_repo, check=True, capture_output=True,
        )

        assert derive_repo_label(worktree_dir) == "pip-skills"

    def test_non_git_dir_returns_none(self, tmp_path):
        assert derive_repo_label(tmp_path) is None

    def test_missing_dir_returns_none(self, tmp_path):
        assert derive_repo_label(tmp_path / "does-not-exist") is None


class TestDeriveRepoRoot:
    def test_main_repo_resolves_to_its_own_path(self, tmp_path):
        main_repo = tmp_path / "pip-skills"
        main_repo.mkdir()
        _git_init(main_repo)
        assert derive_repo_root(main_repo) == main_repo.resolve()

    def test_worktree_resolves_to_main_repo_root_not_worktree_path(self, tmp_path):
        """Mirrors TestDeriveRepoLabel's worktree case: a board.db opened
        from a linked worktree must record the MAIN repo's root path, so
        every worktree of the same repo writes the same `repo_root` value."""
        main_repo = tmp_path / "pip-skills"
        main_repo.mkdir()
        _git_init(main_repo)
        (main_repo / "README.md").write_text("x")
        subprocess.run(["git", "add", "."], cwd=main_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=main_repo, check=True,
            capture_output=True,
        )
        subprocess.run(["git", "branch", "wt-branch"], cwd=main_repo, check=True)

        worktree_dir = tmp_path / "totally-unrelated-worktree-name"
        subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "wt-branch"],
            cwd=main_repo, check=True, capture_output=True,
        )

        assert derive_repo_root(worktree_dir) == main_repo.resolve()

    def test_non_git_dir_returns_none(self, tmp_path):
        assert derive_repo_root(tmp_path) is None

    def test_missing_dir_returns_none(self, tmp_path):
        assert derive_repo_root(tmp_path / "does-not-exist") is None
