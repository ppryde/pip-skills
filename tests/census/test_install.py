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
    code, lines = ins.install(shim, status, CLI, apply=True)
    assert shim.exists()
    assert not status.exists()
    assert any("no status-line script" in line for line in lines)
