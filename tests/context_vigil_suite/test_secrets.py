"""Secrets: nothing context-vigil prints, logs or writes may carry a user's secret.

Every value here is a FAKE canary. No real rc file, settings file or env value is
read: ``iso`` pins HOME, CLAUDE_CONFIG_DIR and the data root into ``tmp_path``.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from context_vigil import census, config, install, launcher, paths, session, state

CANARY = "sk-FAKE-canary"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _no_canary(result) -> None:  # type: ignore[no-untyped-def]
    # assert on a boolean only: a failure must not print the captured output
    leaked = CANARY in result.stdout or CANARY in result.stderr
    assert not leaked, "a canary reached stdout/stderr"


@pytest.fixture
def seeded(home: Path, cfg: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A zsh rc, a 4-space settings.json with secrets, and a status-line script, all
    with canaries on the lines around every edit point."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    rc = home / ".zshrc"
    rc.write_text(f"export A_API_KEY={CANARY}-rc-1\nexport B_TOKEN={CANARY}-rc-2\n"
                  f"export C_SECRET={CANARY}-rc-3\n")
    script = cfg / "statusline.sh"
    script.write_text(f"#!/bin/bash\nexport GITHUB_TOKEN={CANARY}-sl-1\ninput=$(cat)\n"
                      f"export JIRA_TOKEN={CANARY}-sl-2\necho hi\n")
    settings = {
        "env": {"ANTHROPIC_API_KEY": f"{CANARY}-settings-env"},
        "apiKeyHelper": f"echo {CANARY}-helper",
        "hooks": {"Stop": [{"hooks": [{"type": "command",
                                       "command": f"notify {CANARY}-hook"}]}]},
        "statusLine": {"type": "command", "command": f"bash {script}"},
    }
    (cfg / "settings.json").write_text(json.dumps(settings, indent=4) + "\n")
    return {"rc": rc, "script": script, "env": {"SHELL": "/bin/zsh"}}


# --- C1 / C2 / I1: previews print only what we add or remove ---------------------

def test_install_dry_run_prints_no_user_content(run_cli, seeded: dict) -> None:
    result = run_cli("install", "--launcher", "on-demand", env=seeded["env"])
    assert result.returncode == 0, "install dry run failed"
    _no_canary(result)
    out = result.stdout
    ss = dict((e, m) for e, m, _ in install.HOOKS)["SessionStart"]
    assert (f"+ hooks.SessionStart[matcher={ss}]: "
            f"{json.dumps(install.hook_command('session-start'))}") in out
    assert f"+ hooks.Stop: {json.dumps(install.hook_command('stop'))}" in out
    assert f"~ statusLine: spliced capture line into {seeded['script']}" in out
    assert f"{seeded['script']}: adds 3 lines after line 3" in out
    assert install.ingest_command("input") in out
    assert f"{seeded['rc']}: adds 4 lines after line 3" in out
    assert launcher.alias_line("on-demand") in out
    assert "+++" not in out and "@@" not in out


def test_install_apply_and_uninstall_print_no_user_content(run_cli, seeded: dict) -> None:
    applied = run_cli("install", "--yes", "--launcher", "on-demand", env=seeded["env"])
    assert applied.returncode == 0, "install failed"
    _no_canary(applied)
    # a canary right after our rc block too, so uninstall's block has a neighbour both sides
    rc: Path = seeded["rc"]
    rc.write_text(rc.read_text() + f"export D_PASSWORD={CANARY}-rc-4\n")
    for args in (("launcher", "always"), ("launcher", "on-demand", "--yes"),
                 ("uninstall",), ("uninstall", "--yes")):
        result = run_cli(*args, env=seeded["env"])
        assert result.returncode == 0, f"{args} failed"
        _no_canary(result)
    out = run_cli("install", "--launcher", "on-demand", env=seeded["env"]).stdout
    assert "removes our block" not in out  # nothing installed any more
    assert f"{CANARY}-rc-4" in rc.read_text()  # the user's line was kept, never printed


def test_uninstall_says_what_it_removes(run_cli, seeded: dict) -> None:
    assert run_cli("install", "--yes", "--launcher", "on-demand",
                   env=seeded["env"]).returncode == 0
    out = run_cli("uninstall", env=seeded["env"]).stdout
    assert f"{seeded['rc']}: removes our block (4 lines)" in out
    assert f"{seeded['script']}: removes our block (3 lines)" in out
    ss = dict((e, m) for e, m, _ in install.HOOKS)["SessionStart"]
    assert (f"- hooks.SessionStart[matcher={ss}]: "
            f"{json.dumps(install.hook_command('session-start'))}") in out
    assert '"env"' not in out and "ANTHROPIC_API_KEY" not in out and "apiKeyHelper" not in out


def test_launcher_switch_shows_only_our_lines(run_cli, seeded: dict) -> None:
    assert run_cli("launcher", "on-demand", "--yes", env=seeded["env"]).returncode == 0
    result = run_cli("launcher", "always", env=seeded["env"])
    _no_canary(result)
    assert "removes our block (4 lines)" in result.stdout
    assert launcher.alias_line("always") in result.stdout


def test_damaged_rc_block_is_reported_without_content(run_cli, seeded: dict) -> None:
    rc: Path = seeded["rc"]
    rc.write_text(rc.read_text() + f"{launcher.RC_START}\nexport E_KEY={CANARY}-rc-5\n")
    for args in (("uninstall",), ("install", "--launcher", "on-demand"),
                 ("launcher", "on-demand")):
        result = run_cli(*args, env=seeded["env"])
        _no_canary(result)
        assert "look damaged" in result.stdout + result.stderr


def test_canonical_settings_with_adjacent_env_prints_no_env(run_cli, cfg: Path) -> None:
    (cfg / "settings.json").write_text(json.dumps(
        {"model": "opus", "env": {"X_TOKEN": f"{CANARY}-adjacent"}}, indent=2) + "\n")
    for args in (("install",), ("install", "--yes"), ("uninstall",), ("uninstall", "--yes")):
        _no_canary(run_cli(*args))
    data = json.loads((cfg / "settings.json").read_text())
    assert data["env"] == {"X_TOKEN": f"{CANARY}-adjacent"}


def test_plan_change_has_no_text_diff() -> None:
    assert not hasattr(install.Change, "diff")


def test_unchanged_settings_are_not_rewritten(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    data = json.loads((cfg / "settings.json").read_text())
    (cfg / "settings.json").write_text(json.dumps(data, indent=4) + "\n")
    plan = install.plan_install(threshold=None)
    assert all(c.before == c.after for c in plan.changes)


# --- I2: data at rest ------------------------------------------------------------

def test_data_root_and_handoff_are_private(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.write_handoff(scope, "notes")
    root = paths.data_root()
    assert _mode(root) == 0o700
    for d in [scope, *scope.parents]:
        if root in d.parents or d == root:
            assert _mode(d) == 0o700, d
    assert _mode(state.handoff_path(scope)) == 0o600
    state.write_handoff(scope, "second")
    archived = list(state.handoff_archive_dir(scope).iterdir())
    assert archived and all(_mode(f) == 0o600 for f in archived)
    assert _mode(state.handoff_archive_dir(scope)) == 0o700


def test_markers_and_records_are_private(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.pause(scope)
    state.set_gate(scope)
    state.begin_cycle(scope, cooldown=True)
    state.request_clear(paths.scope_dir(repo, "other"), "doc")
    session.save("s1", session.blank())
    with session.locked("s1"):
        pass
    session.learn_window("m", 1000)
    census.ingest(json.dumps({"session_id": "s1", "workspace": {"current_dir": str(repo)}}))
    config.set_value(repo, "context.threshold", "50")
    config.set_value(repo, "context.threshold", "50", worktree=True)
    install.apply(install.plan_install(threshold=None))
    for path in paths.data_root().rglob("*"):
        assert _mode(path) == (0o700 if path.is_dir() else 0o600), path


def test_wider_existing_files_are_tightened_on_next_write(repo: Path) -> None:
    root = paths.data_root()
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    cfg = paths.global_config_path()
    cfg.write_text("{}\n")
    cfg.chmod(0o644)
    config.set_value(repo, "context.threshold", "40")
    assert _mode(cfg) == 0o600 and _mode(root) == 0o700
    scope = paths.scope_dir(repo)
    scope.mkdir(parents=True)
    state.handoff_path(scope).write_text("old")
    state.handoff_path(scope).chmod(0o644)
    state.write_handoff(scope, "new")
    assert _mode(state.handoff_path(scope)) == 0o600
    assert all(_mode(f) == 0o600 for f in state.handoff_archive_dir(scope).iterdir())


def test_atomic_temp_files_are_created_private(repo: Path, iso: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []
    real = os.replace

    def spy(src, dst):  # type: ignore[no-untyped-def]
        seen.append((Path(src).name, _mode(Path(src))))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    config.set_value(repo, "context.threshold", "50")
    state.write_handoff(paths.scope_dir(repo), "doc")
    session.save("s1", session.blank())
    paths.write_private(paths.data_root() / "x.json", "{}")
    assert seen and all(m == 0o600 for _, m in seen), seen


def test_user_file_temp_is_private_before_copymode(home: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    target = home / ".zshrc"
    target.write_text("export X=1\n")
    target.chmod(0o644)
    modes: list = []
    real = shutil.copymode

    def spy(src, dst):  # type: ignore[no-untyped-def]
        modes.append(_mode(Path(dst)))
        return real(src, dst)

    monkeypatch.setattr(shutil, "copymode", spy)
    install.write_atomic(target, "export X=2\n")
    assert modes == [0o600]
    assert _mode(target) == 0o644  # the user's own mode is kept


def test_archive_keeps_newest_twenty_by_default(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    assert config.DEFAULTS["handover.archive_keep"] == 20
    for i in range(25):
        state.write_handoff(scope, f"doc {i}")
        os.utime(state.handoff_path(scope), (1000 + i, 1000 + i))
    archived = list(state.handoff_archive_dir(scope).iterdir())
    assert len(archived) == 20
    bodies = {f.read_text() for f in archived}
    assert "doc 23" in bodies and "doc 0" not in bodies and "doc 3" not in bodies


def test_archive_keep_zero_keeps_none(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.write_handoff(scope, "a", keep=0)
    state.write_handoff(scope, "b", keep=0)
    assert state.consume_handoff(scope, keep=0) == "b"
    archive = state.handoff_archive_dir(scope)
    assert not archive.exists() or not list(archive.iterdir())


def test_archive_keep_is_configurable(run_cli, repo: Path) -> None:
    assert run_cli("config", "set", "handover.archive_keep", "0", cwd=repo).returncode == 0
    assert config.archive_keep(repo) == 0
    assert run_cli("config", "set", "handover.archive_keep", "-1", cwd=repo).returncode == 1


# --- Minors: error messages never echo file content -------------------------------

def test_error_messages_carry_no_canaries(run_cli, cfg: Path, repo: Path) -> None:
    (cfg / "settings.json").write_text('{"env": {"K": "%s-err"}, nope' % CANARY)
    for args in (("install",), ("install", "--yes"), ("uninstall",), ("uninstall", "--yes")):
        result = run_cli(*args)
        assert result.returncode == 1
        _no_canary(result)
    (cfg / "settings.json").write_text(json.dumps(
        {"env": {"K": f"{CANARY}-shape"}, "hooks": {"Stop": f"{CANARY}-hooks"}}))
    for args in (("install",), ("uninstall",)):
        result = run_cli(*args)
        assert result.returncode == 1
        _no_canary(result)
    notes = repo / "notes.md"
    notes.write_text(f"## Goal\n{CANARY}-goal\n## Next Step\n- a {CANARY}\n- b\n")
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 1
    _no_canary(result)
    notes.write_text(f"## Failed Attempts\nNone\n## Next Step\n{CANARY}-x " * 4000)
    result = run_cli("handover", "--file", str(notes), "--no-snapshot", cwd=repo)
    assert result.returncode == 1
    _no_canary(result)
    paths.global_config_path().parent.mkdir(parents=True, exist_ok=True)
    paths.global_config_path().write_text(json.dumps(
        {"context.mode": f"{CANARY}-mode", "context.threshold": f"{CANARY}-thr"}))
    for args in (("config", "get", "context.mode"), ("status",),
                 ("config", "set", "context.threshold", f"{CANARY}-arg"),
                 ("config", "set", "context.mode", f"{CANARY}-arg")):
        _no_canary(run_cli(*args, cwd=repo))


# --- Setup wave: every new output path prints only our strings, paths, line numbers --

def test_status_prints_no_user_content(run_cli, seeded: dict, repo: Path) -> None:
    for args in (("status",), ("install", "--yes", "--launcher", "on-demand"), ("status",)):
        result = run_cli(*args, env=seeded["env"], cwd=repo)
        assert result.returncode == 0, f"{args} failed"
        _no_canary(result)
    settings_path = seeded["script"].parent / "settings.json"
    data = json.loads(settings_path.read_text())
    data["statusLine"]["command"] = f"echo {CANARY}-inline"   # not feeding: the warning path
    settings_path.write_text(json.dumps(data))
    result = run_cli("status", env=seeded["env"], cwd=repo)
    assert "WARNING" in result.stdout
    _no_canary(result)
    settings_path.write_text('{"env": {"K": "' + CANARY + '-bad"}, nope')   # unreadable path
    _no_canary(run_cli("status", env=seeded["env"], cwd=repo))


def test_status_prints_no_env_value(run_cli, repo: Path) -> None:
    env = {"CLAUDE_CONFIG_DIR_EXTRA": f"{CANARY}-env", "PATH_CANARY": f"{CANARY}-path",
           "PATH": os.environ["PATH"] + f":/nonexistent/{CANARY}-path"}
    result = run_cli("status", cwd=repo, env=env)
    _no_canary(result)
    result = run_cli("install", cwd=repo, env=env)   # NO_TMUX text, walkthrough
    _no_canary(result)


@pytest.mark.parametrize("definition", [
    f'claude() {{ CLAUDE_CONFIG_DIR={CANARY}-wrap command claude "$@"; }}',
    f"alias claude='ANTHROPIC_API_KEY={CANARY}-alias claude'",
    f"alias claude-tmux='TOKEN={CANARY}-ct tmux'",
])
def test_wrapper_scan_reports_line_numbers_only(run_cli, seeded: dict, definition: str) -> None:
    rc: Path = seeded["rc"]
    rc.write_text(rc.read_text() + definition + "\n")
    for args in (("install", "--launcher", "on-demand"), ("install", "--launcher", "always"),
                 ("install", "--yes", "--launcher", "always", "--confirm-always"),
                 ("launcher", "always"), ("launcher", "on-demand"),
                 ("launcher", "always", "--yes", "--confirm-always")):
        result = run_cli(*args, env=seeded["env"])
        _no_canary(result)
        if "claude-tmux=" not in definition or "on-demand" in args:
            assert f"{rc}:4" in result.stdout + result.stderr, args


def test_bash_caveat_and_closing_lines_print_no_user_content(run_cli, home: Path) -> None:
    rc = home / ".bashrc"
    rc.write_text(f"export A_TOKEN={CANARY}-bash\n")
    (home / ".bash_profile").write_text(f"export B_TOKEN={CANARY}-profile\n")
    env = {"SHELL": "/bin/bash"}
    for args in (("install", "--launcher", "on-demand"),
                 ("install", "--yes", "--launcher", "on-demand"), ("launcher", "on-demand")):
        _no_canary(run_cli(*args, env=env))


def test_resume_fallback_and_cap_print_no_other_content(run_cli, repo: Path) -> None:
    # the handover itself is printed by design; nothing else (paths' neighbours) is
    state.request_clear(paths.worktree_dir(repo), "PLAIN DOC")
    env = {"TMUX": "/tmp/fake,1,0", "TMUX_PANE": "%3", "CONTEXT_VIGIL_SESSION": "cc-r-1"}
    (paths.data_root() / "stray.txt").write_text(f"{CANARY}-stray\n")
    for args in (("status",), ("handover", "--resume")):
        _no_canary(run_cli(*args, cwd=repo, env=env))


# --- I3: the suite never hands the real environment to anything that records it ----

def test_iso_scrubs_secret_shaped_env() -> None:
    from .conftest import SECRET_NAME
    left = [n for n in os.environ
            if SECRET_NAME.search(n) or n.startswith(("ANTHROPIC_", "AWS_"))]
    assert left == []


def test_leak_guard_finds_a_planted_value_by_file_only(iso: Path) -> None:
    from .conftest import leaked_files
    (iso / "log").write_text(f"claude key={CANARY}-guard\n")
    (iso / "clean").write_text("nothing here\n")
    assert leaked_files(iso, (f"{CANARY}-guard".encode(),)) == [iso / "log"]
    assert leaked_files(iso, ()) == []
