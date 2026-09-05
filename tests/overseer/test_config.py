import json
import os
import sqlite3
from pathlib import Path
import pytest
from scripts import config
from scripts.store import derive_repo_label, derive_repo_root

from factories import git_init


def _init_git(root: Path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _seed_plain_board(plain: Path, repo_root: "str | None"):
    """Create a legacy plain `overseer/<label>/board.db` with (or without) a
    `meta.repo_root` value, WITHOUT importing scripts.db (config._owns_plain
    reads it raw, so tests seed it raw too)."""
    plain.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(plain / "board.db"))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    if repo_root is not None:
        conn.execute("INSERT INTO meta(key, value) VALUES('repo_root', ?)", (repo_root,))
    conn.commit()
    conn.close()


def test_central_root_defaults_to_config_dir(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    got = config.central_root(repo)
    # Fresh repo (no legacy plain folder) → the hash-disambiguated folder.
    canonical = derive_repo_root(repo)
    assert got == cfgdir / "overseer" / f"myrepo-{config._short_hash(canonical)}"


def test_central_root_same_basename_different_roots_never_collide(tmp_path, monkeypatch):
    """I2: two repos with the SAME basename but DIFFERENT canonical roots must
    resolve to DIFFERENT central folders — no shared board.db, no cross-repo
    backup leak."""
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    work = tmp_path / "work" / "api"; work.mkdir(parents=True); _init_git(work)
    personal = tmp_path / "personal" / "api"; personal.mkdir(parents=True); _init_git(personal)
    got_work = config.central_root(work)
    got_personal = config.central_root(personal)
    assert got_work != got_personal
    assert got_work.name.startswith("api-")
    assert got_personal.name.startswith("api-")


def test_central_root_adopts_legacy_plain_folder_owned_by_this_repo(tmp_path, monkeypatch):
    """Back-compat: an existing plain `overseer/<label>/` folder whose board.db
    records THIS repo as owner is returned as-is (no hash, no move)."""
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    canonical = derive_repo_root(repo)
    plain = cfgdir / "overseer" / "myrepo"
    _seed_plain_board(plain, str(canonical.resolve()))
    got = config.central_root(repo)
    assert got == plain
    assert plain.exists()  # untouched, not moved


def test_central_root_skips_legacy_plain_folder_owned_by_other_repo(tmp_path, monkeypatch):
    """A plain folder whose board.db names a DIFFERENT repo must NOT be
    adopted — the second colliding repo gets the hashed folder; the plain
    folder is left untouched."""
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    canonical = derive_repo_root(repo)
    plain = cfgdir / "overseer" / "myrepo"
    _seed_plain_board(plain, "/some/other/repo/root")
    got = config.central_root(repo)
    assert got == cfgdir / "overseer" / f"myrepo-{config._short_hash(canonical)}"
    assert got != plain
    # plain folder left untouched, still owned by the other repo
    assert (plain / "board.db").exists()


def test_central_root_adopts_truly_legacy_plain_folder_without_repo_root_meta(tmp_path, monkeypatch):
    """A plain folder with a board.db but NO repo_root meta is unclaimed →
    treated as ours (returns plain), preserving the common single-repo path."""
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    plain = cfgdir / "overseer" / "myrepo"
    _seed_plain_board(plain, None)  # board.db exists, no repo_root meta
    got = config.central_root(repo)
    assert got == plain


def test_short_hash_stable_across_worktrees_of_same_root(tmp_path, monkeypatch):
    """Hash is a function of the canonical root only: two worktree paths that
    resolve to the same derive_repo_root land on the same hashed folder."""
    import subprocess
    main_repo = tmp_path / "main"; main_repo.mkdir(); _init_git(main_repo)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=main_repo, check=True)
    (main_repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main_repo, check=True)
    worktree = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-b", "feature", str(worktree)],
                   cwd=main_repo, check=True)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    assert derive_repo_root(worktree) == main_repo.resolve()
    assert config.central_root(main_repo) == config.central_root(worktree)


def test_central_root_honours_config_local(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    (repo / ".overseer").mkdir()
    (repo / ".overseer" / "config.local.json").write_text(
        json.dumps({"central_dir": str(tmp_path / "elsewhere")})
    )
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    assert config.central_root(repo) == tmp_path / "elsewhere"


def test_central_root_env_wins(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    (repo / ".overseer").mkdir()
    (repo / ".overseer" / "config.local.json").write_text(
        json.dumps({"central_dir": str(tmp_path / "elsewhere")})
    )
    monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "envwins"))
    assert config.central_root(repo) == tmp_path / "envwins"


def test_backup_dir_default(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    assert config.backup_dir(repo) == repo / ".overseer" / "backups"


def test_backup_dir_resolves_relative_to_passed_root_not_main_repo_root(tmp_path, monkeypatch):
    """Regression: backup_dir must follow the ACTUAL working tree passed in
    (a linked worktree), never `derive_repo_root` (the main repo root) —
    the committed backup must ride whichever branch is being pushed. Uses a
    real linked worktree, not a bare simulation, to also prove
    `derive_repo_root(worktree) != worktree` here (i.e. the worktree really
    is a distinct root from main, so this exercises the actual divergence
    the bug hinged on)."""
    import subprocess
    main_repo = tmp_path / "main"; main_repo.mkdir(); _init_git(main_repo)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=main_repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=main_repo, check=True)
    (main_repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main_repo, check=True)

    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feature", str(worktree)],
        cwd=main_repo, check=True,
    )

    from scripts.store import derive_repo_root
    assert derive_repo_root(worktree) == main_repo.resolve()

    assert config.backup_dir(worktree) == worktree / ".overseer" / "backups"
    # relative custom pref (config.json lives at the shared MAIN root, same
    # as `central_root`/`repo_config_dir` — only `backup_dir`'s RESOLUTION
    # target changes) still resolves the relative path against the
    # worktree, not main
    (main_repo / ".overseer").mkdir(parents=True, exist_ok=True)
    (main_repo / ".overseer" / "config.json").write_text(
        json.dumps({"backup_dir": "custom/backups"})
    )
    assert config.backup_dir(worktree) == worktree / "custom" / "backups"


def test_plain_owner_reads_board_at_path_with_special_chars(tmp_path):
    # A central path containing a '#' (URI fragment delimiter) or a space must
    # be percent-encoded when building the sqlite file: URI. Unencoded, sqlite
    # mis-parses the path and the open fails, so _plain_owner falsely returns
    # "unknown" — which would wrongly adopt a folder that isn't ours (WF-050).
    owner_root = "/some/canonical/root"
    plain = tmp_path / "weird #dir with space" / "api"
    _seed_plain_board(plain, owner_root)
    assert config._plain_owner(plain) == owner_root


class TestClaudeDirs:
    """Multi-account: `config.claude_dirs()` is the primary dir plus the
    `CLAUDE_CONFIG_DIRS` env list plus the machine config's `claude_dirs`,
    existing dirs only, deduplicated, primary first. `central_root` searches
    every one for an existing board before defaulting to the primary."""

    def _dirs(self, tmp_path, monkeypatch, *names):
        made = []
        for name in names:
            d = tmp_path / name
            d.mkdir(parents=True, exist_ok=True)
            made.append(d)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(made[0]))
        monkeypatch.delenv("CLAUDE_CONFIG_DIRS", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        return made

    def test_primary_only_by_default(self, tmp_path, monkeypatch):
        primary, = self._dirs(tmp_path, monkeypatch, "claude")
        assert config.claude_dirs() == [primary]
        assert config.load_machine_config() == {}

    def test_add_and_remove_edit_the_machine_config(self, tmp_path, monkeypatch):
        primary, personal = self._dirs(tmp_path, monkeypatch, "claude", "claude-personal")
        assert config.add_claude_dir(personal) == [str(personal)]
        assert config.machine_config_path() == primary / "overseer" / "config.json"
        assert json.loads(config.machine_config_path().read_text()) == {"claude_dirs": [str(personal)]}
        assert config.claude_dirs() == [primary, personal]
        # Adding twice is idempotent; removing clears it.
        assert config.add_claude_dir(personal) == [str(personal)]
        assert config.remove_claude_dir(personal) == []
        assert config.claude_dirs() == [primary]

    def test_env_list_and_dedup_and_missing(self, tmp_path, monkeypatch):
        primary, personal, work = self._dirs(tmp_path, monkeypatch, "claude", "personal", "work")
        config.add_claude_dir(work)
        monkeypatch.setenv(
            "CLAUDE_CONFIG_DIRS",
            os.pathsep.join([str(personal), str(work), str(tmp_path / "gone"), str(primary)]),
        )
        # Env entries come before file entries; the primary is never listed
        # twice; a dir that does not exist is dropped.
        assert config.claude_dirs() == [primary, personal, work]

    def test_malformed_machine_config_raises(self, tmp_path, monkeypatch):
        primary, = self._dirs(tmp_path, monkeypatch, "claude")
        config.machine_config_path().parent.mkdir(parents=True)
        config.machine_config_path().write_text("{not json")
        with pytest.raises(ValueError):
            config.claude_dirs()

    def test_central_root_finds_a_board_under_another_watched_dir(self, tmp_path, monkeypatch):
        primary, personal = self._dirs(tmp_path, monkeypatch, "claude", "claude-personal")
        repo = tmp_path / "repo"
        repo.mkdir()
        git_init(repo)
        label = derive_repo_label(repo)
        canonical = derive_repo_root(repo)
        elsewhere = personal / "overseer" / f"{label}-{config._short_hash(canonical)}"
        elsewhere.mkdir(parents=True)
        # Not watched yet: the primary's (non-existent) folder is the answer.
        assert config.central_root(repo) == primary / "overseer" / elsewhere.name
        # Watched: the existing folder under the second account wins.
        config.add_claude_dir(personal)
        assert config.central_root(repo) == elsewhere
        # A fresh repo still defaults to the primary for creation.
        other = tmp_path / "other"
        other.mkdir()
        git_init(other)
        assert config.central_root(other).parent == primary / "overseer"
