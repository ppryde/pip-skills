"""WF-100 C2: live vs archived Claude config dirs, and the ONE discovery helper.

An archived dir holds real board copies (a backup of an old account); it must
never shadow a live board, never be adopted by the CLI, and never receive
writes. `boards.discover()` flags it; consumers filter.
"""
import json
from pathlib import Path

import pytest
from factories import git_init
from scripts import boards, config, db
from scripts.cli import main


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """primary + live2 + listed archive + a dir under .../backups/x, all real."""
    for var in ("OVERSEER_DB", "OVERSEER_CENTRAL", "CLAUDE_CONFIG_DIRS"):
        monkeypatch.delenv(var, raising=False)
    dirs = {
        "primary": tmp_path / "cfg-primary",
        "live2": tmp_path / "cfg-live2",
        "listed": tmp_path / "somewhere" / "old-account",
        "seg": tmp_path / "claude-transcript-archive" / "backups" / "x",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(dirs["primary"]))
    config.save_machine_config({
        "claude_dirs": [str(dirs["listed"]), str(dirs["seg"]), str(dirs["live2"])],
        "archive_dirs": [str(dirs["listed"])],
        "volumes": [{"name": "v", "claude_dir": ".config/claude"}],
        "path_map": {"/a": "/b"},
    })
    boards._discover_cache_clear()
    return dirs


def seed(tmp_path, monkeypatch, name: str, config_dir: Path) -> Path:
    """A git repo with a board under `<config_dir>/overseer/<name>/`."""
    repo = tmp_path / "repos" / name
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        git_init(repo)
    folder = config_dir / "overseer" / f"{name}-seed"
    monkeypatch.setenv("OVERSEER_CENTRAL", str(folder))
    db.connect(repo, migrate=False).close()
    monkeypatch.delenv("OVERSEER_CENTRAL")
    return repo


class TestDetection:
    def test_listed_dir_is_archived(self, machine):
        assert config.is_archived(machine["listed"])

    def test_segment_heuristic_catches_backup_and_archive_names(self, machine, tmp_path):
        assert config.is_archived(machine["seg"])
        for seg in ("Backup", "BACKUPS", "archive", "Archives"):
            assert config.is_archived(tmp_path / seg / "cfg")

    def test_plain_dir_is_live(self, machine):
        assert not config.is_archived(machine["live2"])
        assert not config.is_archived(machine["primary"])

    def test_primary_is_never_archived_even_when_listed_or_named(self, tmp_path, monkeypatch, capsys):
        primary = tmp_path / "backups" / "cfg"
        primary.mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(primary))
        config.save_machine_config({"archive_dirs": [str(primary)]})
        assert not config.is_archived(primary)
        assert "primary" in capsys.readouterr().err

    def test_symlinked_archive_dir_is_compared_resolved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        target = tmp_path / "plain-target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target)
        config.save_machine_config({"archive_dirs": [str(link)]})
        assert config.is_archived(target)
        assert config.is_archived(link)

    def test_live_claude_dirs_excludes_archives(self, machine):
        live = [p.resolve() for p in config.live_claude_dirs()]
        assert live == [machine["primary"].resolve(), machine["live2"].resolve()]
        assert machine["listed"].resolve() in [p.resolve() for p in config.claude_dirs()]

    def test_is_archived_path(self, machine, tmp_path):
        assert config.is_archived_path(machine["listed"] / "overseer" / "r" / "board.db")
        assert config.is_archived_path(machine["seg"] / "overseer" / "r")
        assert not config.is_archived_path(machine["live2"] / "overseer" / "r")
        # outside every claude dir: never archived, even under a `backups` segment
        assert not config.is_archived_path(tmp_path / "repo" / "backups" / "central")

    def test_claude_dirs_edit_preserves_other_keys(self, machine):
        extra = machine["live2"].parent / "extra"
        extra.mkdir()
        config.add_claude_dir(extra)
        config.remove_claude_dir(extra)
        cfg = config.load_machine_config()
        assert cfg["archive_dirs"] == [str(machine["listed"])]
        assert cfg["volumes"] and cfg["path_map"] == {"/a": "/b"}


class TestDiscover:
    def test_archive_listed_before_live_still_loses(self, machine, tmp_path, monkeypatch):
        repo = seed(tmp_path, monkeypatch, "shared", machine["live2"])
        seed(tmp_path, monkeypatch, "shared", machine["listed"])  # same repo, archived copy
        seed(tmp_path, monkeypatch, "shared", machine["seg"])
        found = boards.discover()
        assert len(found) == 1
        assert found[0]["archived"] is False
        assert Path(found[0]["root"]).resolve() == repo.resolve()
        assert Path(found[0]["board_dir"]).is_relative_to(machine["live2"])

    def test_archive_only_repo_is_listed_flagged(self, machine, tmp_path, monkeypatch):
        repo = seed(tmp_path, monkeypatch, "old", machine["listed"])
        found = boards.discover()
        assert [(e["label"], e["archived"]) for e in found] == [("old", True)]
        assert [e for e in found if not e["archived"]] == []
        assert Path(found[0]["root"]).resolve() == repo.resolve()

    def test_entry_shape(self, machine, tmp_path, monkeypatch):
        seed(tmp_path, monkeypatch, "r", machine["primary"])
        (entry,) = boards.discover()
        assert set(entry) == {"label", "root", "board_dir", "archived", "aliases"}
        assert entry["aliases"] == []

    def test_aliases_listed_for_live_roots(self, machine, tmp_path, monkeypatch):
        repo = seed(tmp_path, monkeypatch, "r", machine["primary"])
        cfg = config.load_machine_config()
        cfg["aliases"] = {"old-name": str(repo), "elsewhere": str(tmp_path / "nope")}
        config.save_machine_config(cfg)
        boards._discover_cache_clear()
        (entry,) = boards.discover()
        assert entry["aliases"] == ["old-name"]

    def test_cache_hits_within_ttl_and_clears(self, machine, tmp_path, monkeypatch):
        seed(tmp_path, monkeypatch, "a", machine["primary"])
        assert len(boards.discover()) == 1
        seed(tmp_path, monkeypatch, "b", machine["primary"])
        assert len(boards.discover()) == 1  # cached
        boards._discover_cache_clear()
        assert len(boards.discover()) == 2

    def test_cache_key_follows_config(self, machine, tmp_path, monkeypatch):
        seed(tmp_path, monkeypatch, "a", machine["listed"])
        assert [e["archived"] for e in boards.discover()] == [True]
        config.save_machine_config({"claude_dirs": [str(machine["listed"])]})  # no longer archived
        assert [e["archived"] for e in boards.discover()] == [False]

    def test_label_computed_once_per_root(self, machine, tmp_path, monkeypatch):
        seed(tmp_path, monkeypatch, "a", machine["primary"])
        seed(tmp_path, monkeypatch, "a", machine["live2"])
        calls = []
        real = boards.derive_repo_label
        monkeypatch.setattr(boards, "derive_repo_label", lambda p: calls.append(p) or real(p))
        boards.discover()
        assert len(calls) == 1


class TestCentralRootSkipsArchives:
    def test_archive_board_is_never_adopted(self, machine, tmp_path, monkeypatch):
        repo = seed(tmp_path, monkeypatch, "only-archived", machine["listed"])
        # name the seeded archive folder the way the ordered walk would look it up
        label = config.derive_repo_label(repo)
        archived_folder = machine["listed"] / "overseer" / f"{label}-{config._short_hash(config.derive_repo_root(repo))}"
        archived_folder.mkdir(parents=True)
        got = config.central_root(repo)
        assert not Path(got).is_relative_to(machine["listed"])
        assert Path(got).is_relative_to(machine["primary"])  # fresh path under the primary

    def test_live_board_is_still_adopted(self, machine, tmp_path, monkeypatch):
        repo = tmp_path / "repos" / "lv"
        repo.mkdir(parents=True)
        git_init(repo)
        label = config.derive_repo_label(repo)
        folder = machine["live2"] / "overseer" / f"{label}-{config._short_hash(config.derive_repo_root(repo))}"
        folder.mkdir(parents=True)
        assert Path(config.central_root(repo)) == folder


class TestReposVerb:
    def test_repos_json_marks_archived_and_keeps_label_root(self, machine, tmp_path, monkeypatch, capsys):
        live = seed(tmp_path, monkeypatch, "live-r", machine["live2"])
        old = seed(tmp_path, monkeypatch, "old-r", machine["seg"])
        capsys.readouterr()
        assert main(["--root", str(tmp_path), "repos", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        by = {r["label"]: r for r in data}
        assert by["old-r"]["archived"] is True and by["live-r"]["archived"] is False
        # the dashboard's existing readers only look at label/root
        assert Path(by["live-r"]["root"]).resolve() == live.resolve()
        assert Path(by["old-r"]["root"]).resolve() == old.resolve()

    def test_repos_text_marks_archived_and_aliases(self, machine, tmp_path, monkeypatch, capsys):
        live = seed(tmp_path, monkeypatch, "live-r", machine["live2"])
        seed(tmp_path, monkeypatch, "old-r", machine["listed"])
        cfg = config.load_machine_config()
        cfg["aliases"] = {"nick": str(live)}
        config.save_machine_config(cfg)
        capsys.readouterr()
        assert main(["--root", str(tmp_path), "repos"]) == 0
        out = capsys.readouterr().out
        assert "old-r [archived]:" in out
        assert "live-r [nick]:" in out


class TestReadOnlyOpen:
    """OVERSEER_READONLY=1: `connect_at` opens `mode=ro&immutable=1` and
    touches nothing (no WAL pragma, no -wal/-shm, no migrate, no stamp)."""

    def test_readonly_connect_reads_and_creates_no_files(self, tmp_path, monkeypatch):
        repo = tmp_path / "r"
        repo.mkdir()
        git_init(repo)
        folder = tmp_path / "central"
        monkeypatch.setenv("OVERSEER_CENTRAL", str(folder))
        monkeypatch.delenv("OVERSEER_DB")
        conn = db.connect(repo, migrate=False)
        conn.execute("INSERT INTO label_colors(name, color_key) VALUES ('a', 'sky')")
        conn.commit()
        conn.close()
        before = sorted(p.name for p in folder.iterdir())
        monkeypatch.setenv("OVERSEER_READONLY", "1")

        ro = db.connect(repo)
        assert db.load_label_colors(ro) == {"a": "sky"}
        with pytest.raises(Exception, match="readonly"):
            ro.execute("INSERT INTO label_colors(name, color_key) VALUES ('b', 'sky')")
        ro.close()

        assert sorted(p.name for p in folder.iterdir()) == before

    def test_readonly_refuses_an_unupgraded_board_instead_of_writing(self, tmp_path, monkeypatch):
        import sqlite3
        folder = tmp_path / "central"
        folder.mkdir()
        sqlite3.connect(folder / "board.db").close()  # user_version 0
        monkeypatch.setenv("OVERSEER_CENTRAL", str(folder))
        monkeypatch.delenv("OVERSEER_DB")
        monkeypatch.setenv("OVERSEER_READONLY", "1")
        with pytest.raises(sqlite3.OperationalError, match="read-only"):
            db.connect(tmp_path)
