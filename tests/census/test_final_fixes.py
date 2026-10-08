"""Final-review fix wave: purge safety, self-healing launcher, atomic-write retry,
custom v1 file name, account-rooted status-line default."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import cli
from scripts import install as ins
from scripts import store as st

CLI = Path("/opt/plugins/census/scripts/cli.py")


# 1. purge deletes only census-owned entries -------------------------------


def _census_files(data: Path) -> None:
    (data / "sessions").mkdir(parents=True)
    (data / "sessions" / "s1.json").write_text("{}")
    for name in ("limits.json", "status.json", "status.json.lock", "status.json.v1-migrated",
                 ".migrate.lock", ".limits.abc.tmp"):
        (data / name).write_text("")


def test_purge_of_pure_census_dir_removes_it(tmp_path):
    data = tmp_path / "census"
    _census_files(data)
    code, lines = ins.uninstall(tmp_path / "nope", tmp_path / "nope.sh", data, apply=True)
    assert code == 0 and not data.exists()
    assert any("sessions" in line for line in lines)


def test_purge_keeps_dir_with_unrelated_files(tmp_path):
    data = tmp_path / "home"
    _census_files(data)
    (data / "precious.txt").write_text("mine")
    (data / "other").mkdir()
    (data / "other" / "x").write_text("mine")
    _, lines = ins.uninstall(tmp_path / "nope", tmp_path / "nope.sh", data, apply=True)
    assert (data / "precious.txt").read_text() == "mine"
    assert (data / "other" / "x").exists()
    assert sorted(p.name for p in data.iterdir()) == ["other", "precious.txt"]
    assert any("kept" in line for line in lines)


def test_purge_dry_run_changes_nothing(tmp_path):
    data = tmp_path / "census"
    _census_files(data)
    ins.uninstall(tmp_path / "nope", tmp_path / "nope.sh", data, apply=False)
    assert (data / "limits.json").exists() and (data / "sessions" / "s1.json").exists()


def test_cli_purge_with_json_store_never_removes_parent(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "keep.txt").write_text("x")
    (home / "census.json").write_text("{}")
    monkeypatch.setenv("CENSUS_STORE", str(home / "census.json"))
    args = ["--shim", str(tmp_path / "s"), "--statusline", str(tmp_path / "none.sh")]
    assert cli.main(["uninstall", "--purge", "--yes", *args]) == 0
    assert (home / "keep.txt").read_text() == "x"


# 2. launcher follows census upgrades --------------------------------------


def _fake_cache(tmp_path, versions, orphaned=()):
    root = tmp_path / "cache" / "mkt" / "census"
    for ver in versions:
        scripts = root / ver / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "cli.py").write_text(f"import sys\nprint('v{ver}', *sys.argv[1:])\n")
    for ver in orphaned:
        (root / ver / ".orphaned_at").write_text("1")
    return root


def _run(shim: Path, *args: str) -> str:
    return subprocess.run(["sh", str(shim), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_shim_follows_upgrade_to_highest_version(tmp_path):
    root = _fake_cache(tmp_path, ["0.9.0", "0.10.0"])
    shim = tmp_path / "census"
    shim.write_text(ins.shim_text(root / "0.9.0" / "scripts" / "cli.py"))
    assert _run(shim, "a") == "v0.9.0 a"
    (root / "0.9.0" / "scripts" / "cli.py").unlink()
    assert _run(shim, "a") == "v0.10.0 a"


def test_shim_skips_orphaned_versions(tmp_path):
    root = _fake_cache(tmp_path, ["0.3.0", "0.9.0", "0.10.0"], orphaned=["0.10.0"])
    shim = tmp_path / "census"
    shim.write_text(ins.shim_text(root / "0.3.0" / "scripts" / "cli.py"))
    (root / "0.3.0" / "scripts" / "cli.py").unlink()
    assert _run(shim) == "v0.9.0"


def test_shim_exits_silently_when_nothing_found(tmp_path):
    root = _fake_cache(tmp_path, ["0.3.0"])
    shim = tmp_path / "census"
    shim.write_text(ins.shim_text(root / "0.3.0" / "scripts" / "cli.py"))
    (root / "0.3.0" / "scripts" / "cli.py").unlink()
    assert _run(shim) == ""


def test_shim_root_empty_for_repo_layout(tmp_path):
    text = ins.shim_text(tmp_path / "plugins" / "census" / "scripts" / "cli.py")
    assert "ROOT=''\n" in text


def test_shim_root_set_for_versioned_layout(tmp_path):
    root = _fake_cache(tmp_path, ["0.3.0"])
    text = ins.shim_text(root / "0.3.0" / "scripts" / "cli.py")
    assert f"ROOT='{root}'\n" in text
    assert "\r" not in text


# 4. Windows atomic-write retry --------------------------------------------


def test_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    real = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError("held open")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    target = tmp_path / "x.json"
    st._atomic_write(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1} and len(calls) == 3
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_atomic_write_gives_up_after_retries(tmp_path, monkeypatch):
    def always(src, dst):
        raise PermissionError("held open")

    monkeypatch.setattr(os, "replace", always)
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        st._atomic_write(tmp_path / "x.json", {})
    assert list(tmp_path.iterdir()) == []


# 5. custom v1 file name migrates ------------------------------------------


def test_custom_named_v1_file_migrates(tmp_path, monkeypatch):
    legacy = tmp_path / "x" / "foo.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"version": 1, "limits": None, "sessions": {
        "s1": {"worktree_cwd": "/wt/a", "updated_at": 100.0, "payload": {}}}}))
    (tmp_path / "x" / "foo.json.lock").write_text("")
    monkeypatch.setenv("CENSUS_STORE", str(legacy))
    assert st.store_path() == legacy and st.census_dir() == legacy.parent
    assert st.migrate(now=200.0) is True
    assert not legacy.exists()
    assert (tmp_path / "x" / "foo.json.v1-migrated").exists()
    assert not (tmp_path / "x" / "foo.json.lock").exists()
    assert st.session_path("s1").exists()


# 6. status-line default follows CLAUDE_CONFIG_DIR -------------------------


def test_statusline_default_follows_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "acct"))
    assert cli._statusline_path() == tmp_path / "acct" / "statusline-command.sh"
