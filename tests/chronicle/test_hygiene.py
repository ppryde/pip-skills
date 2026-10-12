"""CH-5 (default-dir account fallback), CH-15 (one validator, one config writer,
hardened legacy pull-volume)."""
import json
import os
from pathlib import Path

from scripts import cli, store, volumes


def _write_claude_json(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"oauthAccount": {"accountUuid": uuid, "emailAddress": "a@b.c"}}))


class TestAccountProfileDefaultDir:
    def test_default_dir_falls_back_to_the_file_beside_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude").mkdir()
        _write_claude_json(tmp_path / ".claude.json", "acc-default")
        got = store.account_profile(tmp_path / ".claude")
        assert got == {"accountUuid": "acc-default"}

    def test_its_own_file_wins_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        _write_claude_json(tmp_path / ".claude" / ".claude.json", "own")
        _write_claude_json(tmp_path / ".claude.json", "beside")
        assert store.account_profile(tmp_path / ".claude") == {"accountUuid": "own"}

    def test_a_custom_dir_never_reads_the_home_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        _write_claude_json(tmp_path / ".claude.json", "someone-else")
        custom = tmp_path / ".claude-personal"
        custom.mkdir()
        assert store.account_profile(custom) is None

    def test_no_file_anywhere_is_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude").mkdir()
        assert store.account_profile(tmp_path / ".claude") is None


class TestSharedValidators:
    def test_cli_does_not_redeclare_the_validators(self):
        assert not hasattr(cli, "_VOLUME_RE")
        assert not hasattr(cli, "_SOURCE_RE")
        assert not hasattr(cli, "_IMAGE_RE")


class TestMachineConfigWriter:
    def test_save_volumes_and_remotes_preserve_each_other(self):
        store.save_remotes([store.normalise_remote("r1", "host.example")])
        store.save_volumes([store.normalise_volume("wf-state")])
        data = json.loads(store.config_dir().joinpath(*store.MACHINE_CONFIG_RELPATH).read_text())
        assert [v["name"] for v in data["volumes"]] == ["wf-state"]
        assert [r["name"] for r in data["remotes"]] == ["r1"]

    def test_a_malformed_config_is_not_overwritten(self):
        path = store.config_dir().joinpath(*store.MACHINE_CONFIG_RELPATH)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        try:
            store.save_volumes([])
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")
        assert path.read_text() == "{not json"


class TestUnreadableMachineConfig:
    def test_claude_dirs_and_path_map_survive_an_unreadable_config(self):
        path = store.config_dir().joinpath(*store.MACHINE_CONFIG_RELPATH)
        path.parent.mkdir(parents=True)
        path.write_text('{"path_map": {"/a": "/b"}}')
        path.chmod(0)
        try:
            if os.access(path, os.R_OK):          # running as root: chmod is no barrier
                return
            assert store.path_map() == []
            assert store.claude_dirs() == [store.config_dir()]
        finally:
            path.chmod(0o600)

    def test_path_map_reads_through_the_shared_loader(self):
        path = store.config_dir().joinpath(*store.MACHINE_CONFIG_RELPATH)
        path.parent.mkdir(parents=True)
        path.write_text('{"path_map": {"/a": "/b", "/a/c": "/d"}}')
        assert store.path_map() == [("/a/c", "/d"), ("/a", "/b")]


class TestLegacyPullVolumeHardening:
    def _run(self, monkeypatch, tmp_path, dest):
        calls = []

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr("scripts.cli.subprocess.run", lambda cmd, **k: calls.append(cmd) or R())
        rc = cli.main(["pull-volume", "--volume", "wf", "--dest", str(dest)])
        return rc, calls

    def test_helper_container_has_no_network(self, monkeypatch, tmp_path):
        rc, calls = self._run(monkeypatch, tmp_path, tmp_path)
        assert rc == 0
        cmd = calls[0]
        i = cmd.index("--network")
        assert cmd[i + 1] == "none"

    def test_dest_with_a_colon_is_refused(self, monkeypatch, tmp_path, capsys):
        def boom(*a, **k):
            raise AssertionError("docker must not run")
        monkeypatch.setattr("scripts.cli.subprocess.run", boom)
        bad = tmp_path / "a:ro"
        assert cli.main(["pull-volume", "--volume", "wf", "--dest", str(bad)]) == 2
        assert "dest" in capsys.readouterr().err

    def test_image_validator_is_the_volumes_one(self):
        assert volumes._IMAGE_RE.match("alpine:3.20")


class TestSyncHotPath:
    def test_repo_root_is_asked_of_git_once_per_cwd(self, monkeypatch, tmp_path):
        from scripts import ingest
        calls = []

        class R:
            returncode = 128
            stdout = ""
            stderr = ""

        monkeypatch.setattr(ingest.subprocess, "run", lambda cmd, **k: calls.append(cmd) or R())
        ingest.clear_repo_root_cache()
        for _ in range(5):
            assert ingest.repo_root_of(str(tmp_path)) is None
        assert len(calls) == 1
        ingest.clear_repo_root_cache()
        ingest.repo_root_of(str(tmp_path))
        assert len(calls) == 2

    def test_sync_reads_the_cursors_in_one_query(self, builder, projects):
        from scripts import ingest, store
        for i in range(4):
            type(builder)(projects, session_id=f"s{i}").turn(
                f"m{i}", "2026-09-01T10:00:00.000Z").write()
        conn = store.connect()
        statements = []
        conn.set_trace_callback(statements.append)
        ingest.sync(conn, [builder.projects])
        conn.close()
        per_file = [q for q in statements if q.startswith("SELECT mtime, size FROM cursors")]
        assert per_file == []

    def test_machine_config_is_parsed_once_until_it_changes(self, monkeypatch):
        path = store.config_dir().joinpath(*store.MACHINE_CONFIG_RELPATH)
        path.parent.mkdir(parents=True)
        path.write_text('{"path_map": {"/a": "/b"}}')
        reads = []
        real = Path.read_text
        monkeypatch.setattr(Path, "read_text",
                            lambda self, *a, **k: reads.append(self) or real(self, *a, **k))
        for _ in range(4):
            assert store.path_map() == [("/a", "/b")]
        assert len(reads) == 1
        path.write_text('{"path_map": {"/a": "/b", "/c": "/dd"}}')
        assert len(store.path_map()) == 2

    def test_identity_columns_are_written_in_one_statement(self, builder):
        from scripts import ingest, store
        builder.turn("m1", "2026-09-01T10:00:00.000Z").write()
        conn = store.connect()
        statements = []
        conn.set_trace_callback(statements.append)
        ingest.sync(conn, [builder.projects])
        conn.close()
        identity = [q for q in statements if q.startswith("UPDATE sessions SET")
                    and ("SET cwd =" in q or "project_slug =" in q)]
        assert len(identity) == 1 and "project_slug =" in identity[0] and "cwd =" in identity[0]


class TestReconcileHelpers:
    """RC-7 / RC-10: the reconcile skill's public queries."""

    def test_prefix_priced_models_are_listed_by_pricing_status(self, builder):
        from scripts import cli as cli_mod
        builder.turn("m1", "2026-09-01T10:00:00.000Z", model="claude-opus-5").write()
        builder.turn("m2", "2026-09-01T10:01:00.000Z", model="claude-opus-5-6").write()
        builder.turn("m3", "2026-09-01T10:02:00.000Z", model="mystery-model").write()
        assert cli_mod.main(["sync"]) == 0
        conn = store.connect(readonly=True)
        from scripts import pricerefresh
        out = pricerefresh.status(conn)
        conn.close()
        assert out["prefix_priced"] == [
            {"model": "claude-opus-5-6", "priced_as": "claude-opus-5", "turns": 1}]
        assert [m["model"] for m in out["unpriced_models"]] == ["mystery-model"]

    def test_status_on_a_store_with_no_turns_table_is_empty(self):
        import sqlite3

        from scripts import pricerefresh
        out = pricerefresh.status(sqlite3.connect(":memory:"))
        assert out["prefix_priced"] == [] and out["unpriced_models"] == []

    def test_cost_by_day_and_session_match_summary(self, builder):
        from scripts import report
        for i, ts in enumerate(("2026-09-01T10:00:00.000Z", "2026-09-02T10:00:00.000Z")):
            builder.turn(f"m{i}", ts).write()
        conn = store.connect()
        from scripts import ingest
        ingest.sync(conn, [builder.projects])
        by_day = report.cost_by_day(conn, utc=True)
        total = sum(v["cost_usd"] for v in by_day.values())
        assert sorted(by_day) == ["2026-09-01", "2026-09-02"]
        assert abs(total - report.summary(conn)["totals"]["cost_usd"]) < 1e-9
        ranked = report.cost_by_session(conn, limit=5)
        assert ranked[0]["session_id"] == "s1"
        assert abs(ranked[0]["cost_usd"] - total) < 1e-9
        conn.close()


class TestReconcileReferences:
    """RC-9: the shared skill carries no author identifiers, and its queries run."""

    SKILL_DIR = Path(__file__).resolve().parents[2] / "plugins" / "chronicle" / "skills" / "reconcile"

    def test_no_author_identifiers(self):
        text = "\n".join(p.read_text() for p in (self.SKILL_DIR / "SKILL.md",
                                                  self.SKILL_DIR / "references" / "queries.md"))
        for needle in ("1538875f", "ae34a29e", "wayflyer", "/Users/<you>", "claude-transcript-archive"):
            assert needle not in text, needle

    def test_reconcile_is_manual_only(self):
        head = (self.SKILL_DIR / "SKILL.md").read_text().split("---")[1]
        assert "disable-model-invocation: true" in head

    def test_every_python_block_runs_against_a_store(self, builder, monkeypatch):
        import re

        from scripts import ingest
        builder.turn("m1", "2026-09-01T10:00:00.000Z").write()
        conn = store.connect()
        ingest.sync(conn, [builder.projects])
        acct = "11112222-3333-4444-5555-666677778888"
        conn.execute("UPDATE sessions SET account_uuid = ?", (acct,))
        conn.commit()
        conn.close()
        plugin_root = Path(__file__).resolve().parents[2] / "plugins" / "chronicle"
        monkeypatch.setenv("CHRONICLE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setenv("RECONCILE_DB", str(store.db_path()))
        monkeypatch.setenv("RECONCILE_ACCOUNT", acct)
        monkeypatch.setenv("RECONCILE_ACCOUNT_LABELS", json.dumps({acct[:8]: "Work"}))
        text = (self.SKILL_DIR / "references" / "queries.md").read_text()
        blocks = re.findall(r"```python\n(.*?)```", text, re.S)
        assert len(blocks) >= 8
        ns: dict = {}
        for block in blocks:
            exec(compile(block, "queries.md", "exec"), ns)  # noqa: S102
