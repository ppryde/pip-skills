from __future__ import annotations

import json
from pathlib import Path

import pytest
from context_vigil import install, launcher, paths


@pytest.fixture
def zsh(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    rc = home / ".zshrc"
    rc.write_text("export FOO=1\n")
    return rc


def _change(choice: str) -> install.Change:
    change = launcher.plan_rc(choice)
    assert change is not None
    return change


def test_on_demand_adds_claude_tmux_alias(zsh: Path) -> None:
    change = _change("on-demand")
    assert change.path == zsh
    assert f"alias claude-tmux='{paths.skill_dir()}/scripts/claude-tmux'" in change.after
    assert "alias claude=" not in change.after


def test_always_aliases_claude(zsh: Path) -> None:
    change = _change("always")
    assert f"alias claude='{paths.skill_dir()}/scripts/claude-tmux'" in change.after


def test_switching_choice_replaces_block(zsh: Path) -> None:
    install.apply(install.Plan(changes=[_change("always")]))
    change = _change("on-demand")
    assert change.after.count(launcher.RC_START) == 1
    assert "alias claude=" not in change.after


def test_not_now_removes_block(zsh: Path) -> None:
    install.apply(install.Plan(changes=[_change("on-demand")]))
    assert _change("not-now").after == "export FOO=1\n"


def test_idempotent(zsh: Path) -> None:
    install.apply(install.Plan(changes=[_change("on-demand")]))
    change = _change("on-demand")
    assert change.before == change.after


def test_bash_uses_bashrc(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert launcher.rc_path() == home / ".bashrc"


def test_zdotdir_respected(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("ZDOTDIR", str(iso / "zd"))
    assert launcher.rc_path() == iso / "zd" / ".zshrc"


def test_unknown_shell_has_no_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    assert launcher.rc_path() is None
    assert launcher.plan_rc("on-demand") is None


def test_walkthrough_copy_is_verbatim_and_defaults_to_1(
        monkeypatch: pytest.MonkeyPatch, iso: Path) -> None:
    stub = iso / "tmux"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    text = launcher.walkthrough_text()
    assert "1. On demand (recommended)" in text
    assert "Makes `claude` itself ALWAYS launch inside tmux" in text
    assert "choose 1 and use\n     `claude-tmux` instead" in text
    assert "Choose 1–3 [1]:" in text


def test_walkthrough_without_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", "definitely-not-tmux")
    text = launcher.walkthrough_text()
    assert "tmux not detected" in text and "install tmux" in text
    assert "1. On demand" not in text


def test_install_with_launcher_and_uninstall(zsh: Path, cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None, launcher="always"))
    assert launcher.RC_START in zsh.read_text()
    install.apply(install.plan_uninstall())
    assert zsh.read_text() == "export FOO=1\n"


def test_apply_without_record_does_not_create_install_json(zsh: Path) -> None:
    install.apply(install.Plan(changes=[_change("on-demand")]))
    assert not paths.install_record_path().exists()


def test_apply_without_record_keeps_existing_install_json(zsh: Path, cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    before = paths.install_record_path().read_text()
    install.apply(install.Plan(changes=[_change("on-demand")]))
    assert paths.install_record_path().read_text() == before


def test_rc_edit_preserves_mode_and_follows_symlink(
        home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    real = home / "dotfiles" / "zshrc"
    real.parent.mkdir()
    real.write_text("export FOO=1\n")
    real.chmod(0o600)
    link = home / ".zshrc"
    link.symlink_to(real)
    install.apply(install.Plan(changes=[_change("on-demand")]))
    assert link.is_symlink()
    assert launcher.RC_START in real.read_text()
    assert real.stat().st_mode & 0o777 == 0o600


def test_cli_launcher_always_requires_confirm_flag(run_cli, zsh: Path) -> None:
    result = run_cli("launcher", "always", "--yes")
    assert result.returncode == 1 and "--confirm-always" in result.stderr
    result = run_cli("launcher", "always", "--yes", "--confirm-always")
    assert result.returncode == 0 and "alias claude=" in zsh.read_text()


def test_cli_launcher_dry_run_changes_nothing(run_cli, zsh: Path) -> None:
    result = run_cli("launcher", "on-demand")
    assert result.returncode == 0 and "DRY RUN" in result.stdout
    assert zsh.read_text() == "export FOO=1\n"


def test_cli_launcher_updates_existing_record_only(run_cli, zsh: Path, cfg: Path) -> None:
    result = run_cli("launcher", "on-demand", "--yes")
    assert result.returncode == 0
    assert not paths.install_record_path().exists()
    assert run_cli("install", "--yes").returncode == 0
    result = run_cli("launcher", "on-demand", "--yes")
    assert result.returncode == 0
    record = json.loads(paths.install_record_path().read_text())
    assert record["launcher"] == "on-demand" and record["rc_path"] == str(zsh)
    assert run_cli("uninstall", "--yes").returncode == 0
    assert zsh.read_text() == "export FOO=1\n"


def test_cli_install_always_requires_confirm_flag(run_cli, zsh: Path) -> None:
    result = run_cli("install", "--yes", "--launcher", "always")
    assert result.returncode == 1 and "--confirm-always" in result.stderr
    assert zsh.read_text() == "export FOO=1\n"


def test_cli_install_dry_run_shows_walkthrough(run_cli, zsh: Path) -> None:
    result = run_cli("install")
    assert "tmux not detected" in result.stdout
    assert "If choosing Always, confirm:" in result.stdout


def test_rc_path_is_always_inside_tmp(
        iso: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert launcher.rc_path() == home / ".zshrc"
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert launcher.rc_path() == home / ".bashrc"
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("ZDOTDIR", str(iso / "zd"))
    rc = launcher.rc_path()
    assert rc is not None and iso in rc.parents
