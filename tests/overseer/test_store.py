import subprocess
from pathlib import Path

import pytest

from scripts import config, store
from scripts.models import Card
from scripts.store import (
    derive_repo_label,
    derive_repo_root,
    init_workflow,
    slugify,
    state_root,
)
from factories import git_init as _git_init


def _init_git(root): subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def test_migrate_workflow_copies_once(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    # seed a legacy .workflow tree
    wf = repo / ".workflow"
    (wf / "sprints").mkdir(parents=True)
    (wf / "sprints" / "sprint-1.md").write_text("---\nid: sprint-1\nstatus: active\n---\n")
    (wf / "usage.jsonl").write_text('{"card":"WF-001","tokens":5}\n')
    n = store.migrate_workflow_to_central(repo)
    central = config.central_root(repo)
    assert (central / "sprints" / "sprint-1.md").exists()
    assert (central / "usage.jsonl").exists()
    assert n == 2
    # second run must not overwrite / re-copy
    (central / "usage.jsonl").write_text("LOCAL\n")
    n2 = store.migrate_workflow_to_central(repo)
    assert n2 == 0
    assert (central / "usage.jsonl").read_text() == "LOCAL\n"


def test_migrate_workflow_empty_is_noop(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert store.migrate_workflow_to_central(repo) == 0


def test_migrate_workflow_skips_cards_ledger_and_archived_cards(tmp_path, monkeypatch):
    """cards/, ledger.md, and archive/cards/ are all DB-owned (imported by
    db.migrate_from_workflow) and must NOT be copied into central — but
    archive/corrupt/ (quarantined files, never in the DB) must be kept, and
    the skip must be path-specific rather than a basename match: a file
    literally named ``ledger.md`` nested inside knowledge/ is not the
    top-level generated view and must still be copied."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    wf = repo / ".workflow"

    (wf / "cards").mkdir(parents=True)
    (wf / "cards" / "WF-001-x.md").write_text("card")
    (wf / "ledger.md").write_text("ledger view")
    (wf / "archive" / "cards").mkdir(parents=True)
    (wf / "archive" / "cards" / "WF-002-y.md").write_text("archived card")
    (wf / "archive" / "corrupt").mkdir(parents=True)
    (wf / "archive" / "corrupt" / "bad.md").write_text("quarantined")
    (wf / "sprints").mkdir()
    (wf / "sprints" / "sprint-1.md").write_text("sprint")
    (wf / "usage.jsonl").write_text("usage")
    (wf / "knowledge").mkdir()
    (wf / "knowledge" / "notes.md").write_text("notes")
    # nested file literally named ledger.md — NOT the top-level generated
    # view — must still be copied; the skip is path-specific, not basename.
    (wf / "knowledge" / "ledger.md").write_text("nested ledger, not the view")

    n = store.migrate_workflow_to_central(repo)
    central = config.central_root(repo)

    # skipped
    assert not (central / "cards" / "WF-001-x.md").exists()
    assert not (central / "ledger.md").exists()
    assert not (central / "archive" / "cards" / "WF-002-y.md").exists()

    # kept
    assert (central / "archive" / "corrupt" / "bad.md").exists()
    assert (central / "sprints" / "sprint-1.md").exists()
    assert (central / "usage.jsonl").exists()
    assert (central / "knowledge" / "notes.md").exists()
    assert (central / "knowledge" / "ledger.md").exists()

    assert n == 5  # corrupt/bad.md, sprints/sprint-1.md, usage.jsonl, knowledge/notes.md, knowledge/ledger.md


def test_migrate_workflow_sources_from_derived_main_root_not_connecting_root(tmp_path, monkeypatch):
    """Mirrors db.py's worktree-sourcing guard (see
    test_db.test_import_reads_from_derived_main_root_not_connecting_root):
    migrate_workflow_to_central must read the MAIN repo's .workflow/ (via
    derive_repo_root), not the connecting root's own (possibly empty) tree.
    ``derive_repo_root`` is stubbed here, rather than using a real `git
    worktree`, to isolate the exact behaviour under test."""
    main_root = tmp_path / "main"
    connecting_root = tmp_path / "not-the-main-root"
    main_root.mkdir(); connecting_root.mkdir()
    _init_git(main_root)

    wf = main_root / ".workflow"
    (wf / "sprints").mkdir(parents=True)
    (wf / "sprints" / "sprint-1.md").write_text("sprint")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.setattr(store, "derive_repo_root", lambda p: main_root)

    n = store.migrate_workflow_to_central(connecting_root)
    central = config.central_root(connecting_root)

    assert (central / "sprints" / "sprint-1.md").exists()
    assert n == 1


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


class TestSlug:
    def test_slugify(self):
        assert slugify("Fix auth redirect loop on SSO logout!") == (
            "fix-auth-redirect-loop-on-sso-logout"
        )


class TestStateRoot:
    """``state_root`` is now a thin delegate to ``config.central_root`` (see
    ``TestStateRootDelegatesToConfig`` below); the old ``.workflow/`` vs
    gitignored-``scratch/`` precedence logic it used to implement itself was
    removed in the central-storage migration, so those scenarios no longer
    apply here — they're covered as ``config.central_root`` precedence in
    ``tests/test_config.py`` instead."""

    def test_default_resolves_under_config_dir(self, tmp_path, monkeypatch):
        from scripts import config
        from scripts.store import derive_repo_root
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        cfgdir = tmp_path / "cfg"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
        _git_init(tmp_path)
        # Fresh repo → hash-disambiguated folder (finding I2); see
        # tests/test_config.py for the full precedence/adopt-legacy coverage.
        canonical = derive_repo_root(tmp_path)
        assert state_root(tmp_path) == (
            cfgdir / "overseer" / f"{tmp_path.name}-{config._short_hash(canonical)}"
        )

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
