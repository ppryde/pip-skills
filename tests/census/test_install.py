from pathlib import Path

from scripts import install as ins
from scripts import statusline as sl

CLI = Path("/opt/plugins/census/scripts/cli.py")
SCRIPT = "#!/bin/bash\ninput=$(cat)\necho hi\n"


def _paths(tmp_path):
    shim = tmp_path / "bin" / "census"
    status = tmp_path / "statusline-command.sh"
    status.write_text(SCRIPT)
    return shim, status


def test_shim_points_at_this_plugin_and_finds_an_interpreter():
    text = ins.shim_text(CLI)
    assert ins.SHIM_MARKER in text
    assert "'/opt/plugins/census/scripts/cli.py'" in text
    assert "python3 python" in text
    assert "/usr/bin/python3" not in text


def test_shim_quotes_single_quotes_in_path():
    text = ins.shim_text(Path("/o'brien/cli.py"))
    assert "'/o'\\''brien/cli.py'" in text


def test_dry_run_changes_nothing(tmp_path):
    shim, status = _paths(tmp_path)
    code, lines = ins.install(shim, status, CLI, apply=False)
    assert code == 0
    assert not shim.exists()
    assert status.read_text() == SCRIPT
    assert any("would" in line for line in lines)


def test_install_then_again_is_a_noop(tmp_path):
    shim, status = _paths(tmp_path)
    ins.install(shim, status, CLI, apply=True)
    assert shim.read_text() == ins.shim_text(CLI)
    assert sl.is_installed(status.read_text())
    assert shim.stat().st_mode & 0o111
    first = (shim.read_text(), status.read_text())
    ins.install(shim, status, CLI, apply=True)
    assert (shim.read_text(), status.read_text()) == first


def test_replaces_an_old_census_launcher(tmp_path):
    shim, status = _paths(tmp_path)
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/usr/bin/env bash\n# census launcher — resolve the census plugin CLI\nexit 0\n")
    code, _ = ins.install(shim, status, CLI, apply=True)
    assert code == 0
    assert shim.read_text() == ins.shim_text(CLI)


def test_refuses_an_unrelated_file(tmp_path):
    shim, status = _paths(tmp_path)
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/bin/sh\necho my own tool\n")
    code, lines = ins.install(shim, status, CLI, apply=True)
    assert code == 1
    assert shim.read_text() == "#!/bin/sh\necho my own tool\n"
    assert any(str(shim) in line for line in lines)


def test_uninstall_round_trip_restores_script(tmp_path):
    shim, status = _paths(tmp_path)
    ins.install(shim, status, CLI, apply=True)
    ins.uninstall(shim, status, None, apply=True)
    assert not shim.exists()
    assert status.read_text() == SCRIPT


def test_uninstall_purge_removes_census_dir(tmp_path):
    shim, status = _paths(tmp_path)
    data = tmp_path / "census"
    (data / "sessions").mkdir(parents=True)
    ins.install(shim, status, CLI, apply=True)
    ins.uninstall(shim, status, data, apply=True)
    assert not data.exists()


def test_report_never_prints_user_lines(tmp_path):
    shim, status = _paths(tmp_path)
    _, lines = ins.install(shim, status, CLI, apply=False)
    assert not any("echo hi" in line for line in lines)


def test_missing_statusline_is_reported_not_created(tmp_path):
    shim = tmp_path / "bin" / "census"
    status = tmp_path / "nope.sh"
    _, lines = ins.install(shim, status, CLI, apply=True)
    assert shim.exists()
    assert not status.exists()
    assert any("no status-line script" in line for line in lines)


def test_crlf_statusline_round_trips_and_shim_has_no_cr(tmp_path):
    shim, status = _paths(tmp_path)
    raw = b"#!/bin/bash\r\ninput=$(cat)\r\necho hi\r\n"
    status.write_bytes(raw)
    ins.install(shim, status, CLI, apply=True)
    assert b"\r" not in shim.read_bytes()
    ins.uninstall(shim, status, None, apply=True)
    assert status.read_bytes() == raw


def test_binary_shim_is_refused_and_untouched(tmp_path):
    shim, status = _paths(tmp_path)
    shim.parent.mkdir(parents=True)
    blob = b"\xff\xfe\x00\x80binary"
    shim.write_bytes(blob)
    code, _ = ins.install(shim, status, CLI, apply=True)
    assert code == 1
    ins.uninstall(shim, status, None, apply=True)
    assert shim.read_bytes() == blob


def test_missing_statusline_dry_run_says_dry_run(tmp_path):
    shim = tmp_path / "bin" / "census"
    _, lines = ins.install(shim, tmp_path / "nope.sh", CLI, apply=False)
    assert any("dry run" in line for line in lines)
    assert not shim.exists()


def test_loose_mention_of_census_launcher_is_foreign(tmp_path):
    shim, status = _paths(tmp_path)
    shim.parent.mkdir(parents=True)
    body = "#!/bin/sh\necho mine\necho again\n# see also: census launcher docs\n"
    shim.write_text(body)
    code, _ = ins.install(shim, status, CLI, apply=True)
    assert code == 1
    ins.uninstall(shim, status, None, apply=True)
    assert shim.read_text() == body


def test_uninstall_dry_run_changes_nothing(tmp_path):
    shim, status = _paths(tmp_path)
    data = tmp_path / "census"
    data.mkdir()
    ins.install(shim, status, CLI, apply=True)
    before = (shim.read_bytes(), status.read_bytes())
    _, lines = ins.uninstall(shim, status, data, apply=False)
    assert (shim.read_bytes(), status.read_bytes()) == before
    assert data.exists()
    assert any("would" in line for line in lines)


def test_uninstall_twice_reports_nothing_to_remove(tmp_path):
    shim, status = _paths(tmp_path)
    ins.install(shim, status, CLI, apply=True)
    ins.uninstall(shim, status, None, apply=True)
    _, lines = ins.uninstall(shim, status, None, apply=True)
    assert any("nothing to remove" in line for line in lines)


def test_cli_install_and_uninstall_wiring(tmp_path, monkeypatch, capsys):
    from scripts import cli

    shim, status = _paths(tmp_path)
    args = ["--shim", str(shim), "--script", str(status)]
    assert cli.main(["install", *args]) == 0
    assert not shim.exists()
    assert cli.main(["install", "--yes", *args]) == 0
    assert shim.exists() and sl.is_installed(status.read_text())
    data = tmp_path / "store"
    data.mkdir()
    monkeypatch.setenv("CENSUS_STORE", str(data))
    assert cli.main(["uninstall", "--purge", "--yes", *args]) == 0
    assert not shim.exists() and not data.exists()
    assert status.read_text() == SCRIPT
    capsys.readouterr()
