"""Secrets: nothing context-vigil prints, logs or writes may carry a user's secret.

Every value here is a FAKE canary. No real rc file, settings file or env value is
read: ``iso`` pins HOME, CLAUDE_CONFIG_DIR and the data root into ``tmp_path``.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import time
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
    (root / paths.ROOT_MARKER).write_text("")   # ours, left wider by an older version
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


def test_user_file_temp_stays_private_until_the_rename(home: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    target = home / ".zshrc"
    target.write_text("export X=1\n")
    target.chmod(0o644)
    modes: list = []
    real = os.replace

    def spy(src, dst):  # type: ignore[no-untyped-def]
        modes.append(_mode(Path(src)))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    install.write_atomic(target, "export X=2\n")
    assert modes == [0o600]          # a stranded temp copy is never readable by others
    assert _mode(target) == 0o644    # the user's own mode is restored after the rename


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
    notes = repo.parent / "notes.md"   # never inside the repository
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


# --- Round 3 (adversarial): data root, notes home, --inline, hooks, tracebacks -------

GOOD_NOTES = ("## Goal\nShip it.\n\n## Failed Attempts\nNone\n\n"
              "## Next Step\nRun the tests.\n")


def _git_init(path: Path) -> None:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env,
                   capture_output=True, timeout=30)


def _old(path: Path, seconds: int = 120) -> None:
    then = time.time() - seconds
    os.utime(str(path), (then, then), follow_symlinks=False)


def _one_clean_line(result) -> None:  # type: ignore[no-untyped-def]
    assert result.returncode == 1, "expected a refusal"
    assert "Traceback" not in result.stderr, "a traceback reached stderr"
    assert len(result.stderr.strip().splitlines()) == 1, "expected one error line"


# design I1: where the data root may land

def test_relative_data_root_is_refused(run_cli, repo: Path) -> None:
    env = {"CONTEXT_VIGIL_HOME": ".cv"}
    for args in (("status",), ("pause",), ("handover", "--resume"), ("notes-path",)):
        result = run_cli(*args, cwd=repo, env=env)
        _one_clean_line(result)
        assert "CONTEXT_VIGIL_HOME" in result.stderr and "absolute" in result.stderr, args
    hook = run_cli("hook", "session-start", cwd=repo, env=env,
                   stdin=json.dumps({"cwd": str(repo), "source": "startup"}))
    assert hook.returncode == 0
    assert not (repo / ".cv").exists()


def test_data_root_is_self_ignoring_and_warned_inside_a_git_repo(run_cli, cfg: Path,
                                                                 iso: Path) -> None:
    _git_init(cfg)
    root = cfg / "context-vigil"
    env = {"CONTEXT_VIGIL_HOME": str(root)}
    work = iso / "work"
    work.mkdir()
    notes = iso / "n.md"
    notes.write_text(GOOD_NOTES)
    assert run_cli("install", "--yes", "--launcher", "not-now", env=env,
                   cwd=work).returncode == 0
    assert run_cli("handover", "--file", str(notes), "--no-snapshot", env=env,
                   cwd=work).returncode == 0
    assert (root / ".gitignore").read_text() == "*\n"
    porcelain = subprocess.run(
        ["git", "-C", str(cfg), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, timeout=30,
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}).stdout
    assert "context-vigil" not in porcelain
    for args in (("status",), ("install",)):
        result = run_cli(*args, env=env, cwd=work)
        assert f"WARNING: the data root {root} is inside a git repository" in (
            result.stdout + result.stderr), args


def test_data_root_owned_by_another_user_is_refused(repo: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from context_vigil import hooks
    scope = paths.scope_dir(repo)
    state.write_handoff(scope, f"# planted {CANARY}-planted\n")
    uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    with pytest.raises(paths.UnsafeDataRoot):
        state.write_handoff(scope, "x")
    with pytest.raises(paths.UnsafeDataRoot):
        state.pause(scope)
    assert state.read_handoff(scope) is None
    assert state.consume_handoff(scope) is None
    assert hooks.run("session-start", json.dumps(
        {"cwd": str(repo), "source": "startup"})) is None
    assert hooks.run("session-start", json.dumps({"cwd": str(repo), "source": "clear"})) is None
    monkeypatch.setattr(os, "getuid", lambda: uid)
    assert state.read_handoff(scope) == f"# planted {CANARY}-planted\n"


def test_open_data_root_that_cannot_be_tightened_is_refused(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = paths.data_root()
    root.mkdir(mode=0o700)
    root.chmod(0o770)

    def no_chmod(*_a, **_k):  # type: ignore[no-untyped-def]
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "chmod", no_chmod)
    with pytest.raises(paths.UnsafeDataRoot):
        paths.ensure_dir(paths.scope_dir(repo))


def test_handoff_and_marker_io_never_follow_symlinks(run_cli, repo: Path, iso: Path) -> None:
    victim = iso / "victim.txt"
    victim.write_text(f"{CANARY}-victim\n")
    victim.chmod(0o644)
    scope = paths.scope_dir(repo)
    paths.ensure_dir(scope)
    state.handoff_path(scope).symlink_to(victim)
    assert state.read_handoff(scope) is None
    assert state.consume_handoff(scope) is None
    _no_canary(run_cli("handover", "--resume", cwd=repo))
    _no_canary(run_cli("hook", "session-start", cwd=repo,
                       stdin=json.dumps({"cwd": str(repo), "source": "clear"})))
    for marker in (state.paused_flag(scope), state.gate_marker(scope),
                   state.cooldown_marker(scope)):
        marker.symlink_to(victim)
    with pytest.raises(OSError):
        state.pause(scope)
    with pytest.raises(OSError):
        state.set_gate(scope)
    assert _mode(victim) == 0o644 and victim.read_text() == f"{CANARY}-victim\n"


# design M1 / output M1: SIGKILL residue

def test_temp_files_carry_a_recognisable_prefix(repo: Path, home: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []
    real = os.replace

    def spy(src, dst):  # type: ignore[no-untyped-def]
        seen.append((Path(src).name, _mode(Path(src))))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    state.write_handoff(paths.scope_dir(repo), "doc")
    census.ingest(json.dumps({"session_id": "s1", "workspace": {"current_dir": str(repo)}}))
    install.write_atomic(home / ".zshrc", "export X=1\n")
    assert len(seen) >= 3
    assert all(name.startswith(".cv-tmp.") and mode == 0o600 for name, mode in seen), seen


def test_stale_private_temp_files_are_swept_on_the_next_write(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    paths.ensure_dir(scope)
    stale = scope / ".cv-tmp.handoff.md.abc123.tmp"
    legacy = scope / ".handoff.md.zzz999.tmp"
    fresh = scope / ".cv-tmp.handoff.md.new456.tmp"
    for f in (stale, legacy, fresh):
        f.write_text(f"{CANARY}-stray\n")
    _old(stale)
    _old(legacy)
    state.write_handoff(scope, "doc")
    assert not stale.exists() and not legacy.exists() and fresh.exists()


def test_stale_user_file_temps_are_swept_and_parents_are_private(home: Path) -> None:
    legacy = home / ".zshrc.abcd1234.context-vigil.tmp"
    stale = home / ".cv-tmp..zshrc.x1.context-vigil.tmp"
    fresh = home / ".cv-tmp..zshrc.y2.context-vigil.tmp"
    for f in (legacy, stale, fresh):
        f.write_text(f"export K={CANARY}-stray\n")
    _old(legacy)
    _old(stale)
    install.write_atomic(home / ".zshrc", "export X=1\n")
    assert not legacy.exists() and not stale.exists() and fresh.exists()
    old_mask = os.umask(0)
    try:
        install.write_atomic(home / "zd" / "deep" / ".zshrc", "x\n")
    finally:
        os.umask(old_mask)
    assert _mode(home / "zd") == 0o700 and _mode(home / "zd" / "deep") == 0o700


# design M2 / output I1: handover notes live outside every repository

def test_notes_path_is_private_and_outside_the_repo(run_cli, repo: Path) -> None:
    _git_init(repo)
    result = run_cli("notes-path", cwd=repo)
    assert result.returncode == 0, result.stderr
    notes = Path(result.stdout.strip())
    assert notes.is_file() and _mode(notes) == 0o600
    assert str(notes).startswith(str(paths.data_root()) + os.sep)
    assert not str(notes).startswith(str(repo) + os.sep)
    assert "## Next Step" in notes.read_text()
    notes.write_text(GOOD_NOTES)
    again = run_cli("notes-path", cwd=repo)
    assert Path(again.stdout.strip()) == notes and notes.read_text() == GOOD_NOTES
    done = run_cli("handover", "--file", str(notes), "--no-snapshot", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert "inside a git repository" not in done.stderr
    assert not notes.exists()   # used notes are not left lying around


def test_notes_inside_a_repo_warn_by_path_only(run_cli, repo: Path) -> None:
    _git_init(repo)
    notes = repo / "handover-notes.md"
    notes.write_text(GOOD_NOTES)
    result = run_cli("handover", "--file", str(notes), "--no-snapshot", cwd=repo)
    assert result.returncode == 0, result.stderr
    assert str(notes) in result.stderr and "inside a git repository" in result.stderr
    assert "notes-path" in result.stderr and "Ship it" not in result.stderr
    assert notes.exists()   # the user's file: warned about, never deleted


def test_agent_is_directed_to_the_private_notes_path() -> None:
    from context_vigil import handover, hooks

    from .conftest import SKILL
    for text in (hooks.NUDGE_ATTENDED, hooks.NUDGE_UNATTENDED):
        assert "notes-path" in text and "never" in text and "repositor" in text
    remote = hooks.NUDGE_REMOTE.lower()
    assert "never inline" in remote and ".env" in remote and "secret" in remote
    skill = (SKILL / "SKILL.md").read_text()
    assert "notes-path" in skill and "scratch file" not in skill
    template = handover.template_path().read_text()
    assert "notes-path" in template and "secret" in template


# design I3: --inline

def _remote(repo: Path) -> None:
    config.set_value(repo, "context.mode", "remote")


def _handoff_saved(repo: Path) -> bool:
    return state.handoff_path(paths.scope_dir(repo)).exists()


def test_inline_is_refused_in_local_mode(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "n.md"
    notes.write_text(GOOD_NOTES)
    plain = iso / "plain.md"
    plain.write_text("hello\n")
    result = run_cli("handover", "--file", str(notes), "--inline", str(plain),
                     "--no-snapshot", cwd=repo)
    _one_clean_line(result)
    assert "remote" in result.stderr and not _handoff_saved(repo)
    _remote(repo)
    ok = run_cli("handover", "--file", str(notes), "--inline", str(plain),
                 "--no-snapshot", cwd=repo)
    assert ok.returncode == 0, ok.stderr
    assert "hello" in (state.read_handoff(paths.scope_dir(repo)) or "")


@pytest.mark.parametrize("name", [".env", ".env.local", ".envrc", "server.pem", "tls.key",
                                  "id_ed25519", "aws_credentials", "my-secret.txt", ".netrc",
                                  ".npmrc", ".pypirc", "cert.p12", ".zshrc"])
def test_inline_refuses_secret_bearing_names_even_through_a_symlink(
        run_cli, repo: Path, iso: Path, name: str) -> None:
    _remote(repo)
    notes = iso / "n.md"
    notes.write_text(GOOD_NOTES)
    target = iso / "files" / name
    target.parent.mkdir()
    target.write_text("nothing key-shaped here\n")
    link = iso / "innocuous.txt"
    link.symlink_to(target)
    for given in (target, link):
        result = run_cli("handover", "--file", str(notes), "--inline", str(given),
                         "--no-snapshot", cwd=repo)
        _one_clean_line(result)
        assert str(given) in result.stderr and "nothing key-shaped" not in result.stderr
    assert not _handoff_saved(repo)


@pytest.mark.parametrize("where", [".ssh/config", ".aws/config", ".gnupg/gpg.conf",
                                   ".config/gh/hosts.yml", ".claude/CLAUDE.md",
                                   ".claude-personal/notes.md"])
def test_inline_refuses_files_under_credential_dirs(run_cli, repo: Path, home: Path,
                                                    iso: Path, where: str) -> None:
    _remote(repo)
    notes = iso / "n.md"
    notes.write_text(GOOD_NOTES)
    target = home / where
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("plain words\n")
    result = run_cli("handover", "--file", str(notes), "--inline", str(target),
                     "--no-snapshot", cwd=repo)
    _one_clean_line(result)
    assert str(target) in result.stderr and not _handoff_saved(repo)


def test_inline_refuses_the_config_dir_and_the_data_root(run_cli, repo: Path, cfg: Path,
                                                         iso: Path) -> None:
    _remote(repo)
    notes = iso / "n.md"
    notes.write_text(GOOD_NOTES)
    for target in (cfg / "statusline.sh", paths.data_root() / "census.json"):
        target.write_text("plain words\n")
        result = run_cli("handover", "--file", str(notes), "--inline", str(target),
                         "--no-snapshot", cwd=repo)
        _one_clean_line(result)
        assert str(target) in result.stderr
    assert not _handoff_saved(repo)


# design M7 / output M4: a user's hook is never ours

def test_user_hooks_that_mention_context_vigil_are_kept(run_cli, cfg: Path) -> None:
    user = ['"/x/context-vigil" hook stop; curl https://example.invalid',
            f'"{paths.launcher_path()}" hook session-start --secret {CANARY}-hook',
            "echo context-vigil hook nudge"]
    (cfg / "settings.json").write_text(json.dumps({"hooks": {
        "Notification": [{"hooks": [{"type": "command", "command": user[0]}]}],
        "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command",
                                                           "command": user[1]}]}],
        "Stop": [{"hooks": [{"type": "command", "command": user[2]}]}]}}, indent=2) + "\n")
    for args in (("install", "--yes"), ("uninstall", "--yes")):
        result = run_cli(*args)
        assert result.returncode == 0, args
        _no_canary(result)
        assert "older context-vigil command" not in result.stdout
        data = json.loads((cfg / "settings.json").read_text())
        commands = [h["command"] for entries in data["hooks"].values()
                    for e in entries for h in e["hooks"]]
        for command in user:
            assert command in commands, args


# design M8 / output M3: no traceback, ever

def test_non_utf8_inputs_end_in_one_clean_line(run_cli, repo: Path, iso: Path,
                                               cfg: Path) -> None:
    _remote(repo)
    binary = iso / "bin.md"
    binary.write_bytes(b"\xff\xfe" + CANARY.encode() + b"\n")
    notes = iso / "n.md"
    notes.write_text(GOOD_NOTES)
    for args in (("handover", "--file", str(binary)),
                 ("handover", "--file", str(notes), "--inline", str(binary), "--no-snapshot")):
        result = run_cli(*args, cwd=repo)
        _one_clean_line(result)
        assert str(binary) in result.stderr, args
        _no_canary(result)
    (cfg / "settings.json").write_bytes(b'{"env": {"K": "\xff' + CANARY.encode() + b'"}}')
    for args in (("install",), ("uninstall",)):
        result = run_cli(*args)
        _one_clean_line(result)
        assert str(cfg / "settings.json") in result.stderr, args
        _no_canary(result)


def test_unexpected_errors_print_the_class_name_only(monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture) -> None:
    from context_vigil import cli

    def boom(_args):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"{CANARY}-boom")

    monkeypatch.setattr(cli, "_cmd_status", boom)
    assert cli.main(["status"]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "CONTEXT_VIGIL_DEBUG=1" in err
    assert CANARY not in err and "Traceback" not in err
    monkeypatch.setenv("CONTEXT_VIGIL_DEBUG", "1")
    assert cli.main(["status"]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "boom" in err   # frames, by name
    assert CANARY not in err and "raise RuntimeError" not in err   # no message, no source


# output M2: a hand-edited status-line block is never repointed

def test_hand_edited_statusline_block_is_left_alone(run_cli, cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("#!/bin/bash\ninput=$(cat)\necho hi\n")
    script.chmod(0o755)
    (cfg / "settings.json").write_text(json.dumps(
        {"statusLine": {"type": "command", "command": str(script)}}))
    assert run_cli("install", "--yes").returncode == 0
    edited = script.read_text().replace(
        install.SL_START + "\n",
        install.SL_START + f'\nexport Z="$LEAKY_NAME_1"  # {CANARY}\n')
    script.write_text(edited)
    for args in (("install",), ("install", "--yes")):
        result = run_cli(*args)
        assert result.returncode == 0, args
        _no_canary(result)
        assert "LEAKY_NAME_1" not in result.stdout + result.stderr
        assert f"{script}: lines 3-6" in result.stdout, args
    assert script.read_text() == edited


# design M5 / output M8: the suite's own hygiene

def test_scrub_covers_common_secret_names() -> None:
    from .conftest import is_secret_name
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "GH_PAT", "GITHUB_PAT", "OPENAI_API_KEY",
                 "OPENAI_ORG_ID", "NPM_TOKEN", "DATABASE_URL", "REDIS_URL", "MYSQL_PWD",
                 "PGPASSWORD", "PGPASS", "SENTRY_DSN", "SLACK_WEBHOOK_URL", "DOCKER_PASS",
                 "PRIVATE_SSH", "CERT_PASSPHRASE", "HF_TOKEN", "ANTHROPIC_MODEL",
                 "AWS_REGION", "SSH_AUTH_SOCK"):
        assert is_secret_name(name), name
    for name in ("PATH", "HOME", "PWD", "OLDPWD", "LANG", "TERM", "SHELL", "USER", "TMPDIR"):
        assert not is_secret_name(name), name


def test_run_cli_gets_an_explicit_minimal_env(monkeypatch: pytest.MonkeyPatch,
                                              iso: Path) -> None:
    from .conftest import cli_env
    monkeypatch.setenv("SOME_UNRELATED_VAR", "x")
    env = cli_env({"EXTRA": "1"})
    assert "SOME_UNRELATED_VAR" not in env and env["EXTRA"] == "1"
    assert env["HOME"] == os.environ["HOME"] and "PATH" in env
    assert env["CONTEXT_VIGIL_HOME"] == os.environ["CONTEXT_VIGIL_HOME"]
    assert os.environ["TMPDIR"].startswith(str(iso))   # iso pins TMPDIR too


def test_guard_checks_output_and_never_reprs_secrets() -> None:
    from .conftest import Secrets, check_showlocals, leaked_text
    held = Secrets((b"sk-FAKE-canary-out",))
    assert repr(held) == "<redacted>" and str(held) == "<redacted>"
    assert leaked_text("x sk-FAKE-canary-out y", held)
    assert not leaked_text("clean", held)
    with pytest.raises(pytest.UsageError):
        check_showlocals(True, held)
    check_showlocals(False, held)
    check_showlocals(True, Secrets(()))


def test_archiving_never_chmods_through_a_planted_handoff_link(repo: Path, iso: Path) -> None:
    victim = iso / "victim.txt"
    victim.write_text(f"{CANARY}-victim\n")
    victim.chmod(0o644)
    scope = paths.scope_dir(repo)
    paths.ensure_dir(scope)
    state.handoff_path(scope).symlink_to(victim)
    state.write_handoff(scope, "new doc")
    assert _mode(victim) == 0o644 and victim.read_text() == f"{CANARY}-victim\n"
    assert not any(f.is_symlink() for f in state.handoff_archive_dir(scope).glob("*"))
    assert state.read_handoff(scope) == "new doc"


def test_settings_with_duplicate_keys_are_refused_not_collapsed(run_cli, cfg: Path) -> None:
    text = ('{"env": {"K": "%s-dup-1"}, "model": "a", "env": {"K": "%s-dup-2"}}\n'
            % (CANARY, CANARY))
    (cfg / "settings.json").write_text(text)
    for args in (("install",), ("install", "--yes"), ("uninstall", "--yes")):
        result = run_cli(*args)
        _one_clean_line(result)
        assert "duplicate" in result.stderr and str(cfg / "settings.json") in result.stderr
        _no_canary(result)
        assert '"env"' not in result.stderr
    assert (cfg / "settings.json").read_text() == text


# --- Round 4 (verification): never damage a user's directory -----------------------
# N-2 / N-7: the skill chmods, writes `.gitignore`, sweeps or deletes only inside a
# directory it owns: one it created itself, recorded by ``.context-vigil-root``.

def _dir_state(path: Path) -> tuple:
    return (_mode(path), sorted(os.listdir(str(path))))


@pytest.mark.parametrize("which", ["home", "config", "worktree-root", "filesystem-root"])
def test_data_root_refuses_home_config_dir_repo_root_and_slash(
        run_cli, iso: Path, home: Path, cfg: Path, repo: Path, which: str) -> None:
    target = {"home": home, "config": cfg, "worktree-root": iso / "wt",
              "filesystem-root": Path("/")}[which]
    if which == "worktree-root":
        target.mkdir()
        _git_init(target)
    if which != "filesystem-root":
        (target / "mine.txt").write_text("mine\n")
        target.chmod(0o755)
    before = _dir_state(target)
    env = {"CONTEXT_VIGIL_HOME": str(target)}
    for args in (("notes-path",), ("status",), ("pause",),
                 ("install", "--yes", "--launcher", "not-now")):
        result = run_cli(*args, cwd=repo, env=env)
        _one_clean_line(result)
        assert "refusing" in result.stderr and str(target) in result.stderr, args
    hook = run_cli("hook", "session-start", cwd=repo, env=env,
                   stdin=json.dumps({"cwd": str(repo), "source": "startup"}))
    assert hook.returncode == 0 and hook.stdout == ""
    assert _dir_state(target) == before
    if which == "config":
        assert not (cfg / "settings.json").exists()


def test_data_root_refusal_is_raised_in_process_too(home: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    for target in (home, Path("/")):
        monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(target))
        with pytest.raises(paths.DataRootError):
            paths.data_root()


def test_a_nonempty_foreign_dir_gets_a_subdirectory_of_ours(run_cli, iso: Path,
                                                            repo: Path) -> None:
    shared = iso / "shared"
    shared.mkdir()
    (shared / "README.md").write_text("mine\n")
    shared.chmod(0o755)
    env = {"CONTEXT_VIGIL_HOME": str(shared)}
    result = run_cli("notes-path", cwd=repo, env=env)
    assert result.returncode == 0, result.stderr
    ours = shared / "context-vigil"
    assert result.stdout.strip().startswith(str(ours) + os.sep)
    assert _dir_state(shared) == (0o755, ["README.md", "context-vigil"])
    assert (shared / "README.md").read_text() == "mine\n"
    assert (ours / paths.ROOT_MARKER).is_file() and _mode(ours) == 0o700
    assert (ours / ".gitignore").read_text() == "*\n"
    assert "data: " + str(ours) in run_cli("status", cwd=repo, env=env).stdout


def test_a_foreign_dir_with_a_foreign_subdirectory_is_refused(run_cli, iso: Path,
                                                              repo: Path) -> None:
    shared = iso / "shared"
    (shared / "context-vigil").mkdir(parents=True)
    (shared / "context-vigil" / "notes.txt").write_text("mine\n")
    before = (_dir_state(shared), _dir_state(shared / "context-vigil"))
    result = run_cli("notes-path", cwd=repo, env={"CONTEXT_VIGIL_HOME": str(shared)})
    _one_clean_line(result)
    assert str(shared) in result.stderr and "refusing" in result.stderr
    assert (_dir_state(shared), _dir_state(shared / "context-vigil")) == before


def test_an_empty_dir_and_an_older_versions_root_are_adopted(iso: Path, repo: Path,
                                                             monkeypatch) -> None:
    empty = iso / "empty"
    empty.mkdir(mode=0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(empty))
    assert paths.data_root() == empty
    state.pause(paths.scope_dir(repo))
    assert (empty / paths.ROOT_MARKER).is_file() and _mode(empty) == 0o700
    legacy = iso / "legacy"
    (legacy / "worktrees" / "x").mkdir(parents=True)
    (legacy / "census.json").write_text("{}\n")
    (legacy / ".gitignore").write_text("*\n")
    monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(legacy))
    assert paths.data_root() == legacy
    state.pause(paths.scope_dir(repo))
    assert (legacy / paths.ROOT_MARKER).is_file() and (legacy / "worktrees" / "x").is_dir()


def test_an_unmarked_dir_writable_by_others_is_refused_not_chmodded(iso: Path,
                                                                    repo: Path,
                                                                    monkeypatch) -> None:
    open_dir = iso / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(open_dir))
    with pytest.raises(paths.UnsafeDataRoot):
        state.pause(paths.scope_dir(repo))
    assert _dir_state(open_dir) == (0o777, [])


def test_a_root_of_ours_left_open_is_tightened_by_status(run_cli, repo: Path) -> None:
    state.pause(paths.scope_dir(repo))
    root = paths.data_root()
    root.chmod(0o777)
    assert run_cli("status", cwd=repo).returncode == 0
    assert _mode(root) == 0o700


def test_sweeps_touch_only_our_own_named_regular_files(home: Path, iso: Path,
                                                       repo: Path) -> None:
    # beside a user file: only the temps of THAT file's own writes
    other = home / ".cv-tmp.other.x1.context-vigil.tmp"
    other.write_text("not this write's\n")
    _old(other)
    install.write_atomic(home / ".zshrc", "export X=1\n")
    assert other.exists()
    # a planted symlink with our name is never unlinked, whatever its age
    scope = paths.scope_dir(repo)
    paths.ensure_dir(scope)
    target = iso / "target.txt"
    target.write_text("t\n")
    link = scope / ".cv-tmp.handoff.md.lnk.tmp"
    link.symlink_to(target)
    _old(link)
    state.write_handoff(scope, "doc")
    assert link.is_symlink() and target.exists()
    # write_private outside the data root sweeps nothing
    outside = iso / "outside"
    outside.mkdir()
    stray = outside / ".cv-tmp.f.zz.tmp"
    stray.write_text("x\n")
    _old(stray)
    paths.write_private(outside / "f", "y\n")
    assert stray.exists()


# N-3: every read of a state file goes through the guarded, no-follow reader

def test_state_reads_never_follow_a_symlink(repo: Path, iso: Path) -> None:
    root = paths.data_root()
    paths.ensure_dir(root)
    planted = iso / "planted.json"
    planted.write_text(json.dumps({"context.threshold": 90}))
    paths.global_config_path().symlink_to(planted)
    assert config.threshold(repo) == config.DEFAULTS["context.threshold"]
    install_json = iso / "install.json"
    install_json.write_text(json.dumps({"skill_dir": "/elsewhere"}))
    paths.install_record_path().symlink_to(install_json)
    assert install._read_record() == {}
    paths.windows_path().symlink_to(planted)
    assert session.windows() == {}
    census_json = iso / "census.json"
    census_json.write_text(json.dumps({"version": 1, "sessions": {"s": {"pct": 99}}}))
    paths.census_path().symlink_to(census_json)
    assert census._load(paths.census_path())["sessions"] == {}


def test_status_reports_a_foreign_owned_root(run_cli, repo: Path,
                                             monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture) -> None:
    from context_vigil import cli
    state.pause(paths.scope_dir(repo))
    uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    monkeypatch.chdir(repo)
    assert cli.main(["status"]) == 1
    err = capsys.readouterr().err
    assert "owned by another user" in err and len(err.strip().splitlines()) == 1


# N-4: an unrecorded older install's hook is named, never deleted

def test_an_unrecorded_old_install_hook_is_flagged_not_removed(run_cli, cfg: Path) -> None:
    old = '"/old/skill/scripts/context-vigil" hook session-start'
    (cfg / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": old}]}]}}))
    for args in (("install",), ("install", "--yes", "--launcher", "not-now")):
        result = run_cli(*args)
        assert result.returncode == 0, args
        assert ("MANUAL STEP: hooks.SessionStart: a context-vigil hook from another "
                "install at /old/skill") in result.stdout, args
    commands = [h["command"] for e in json.loads((cfg / "settings.json").read_text())[
        "hooks"]["SessionStart"] for h in e["hooks"]]
    assert old in commands and len(commands) == 2


# N-5: tidying deletes the notes file and nothing else

def test_handover_never_deletes_another_file_under_the_data_root(run_cli, repo: Path,
                                                                 iso: Path) -> None:
    other = paths.worktree_dir(iso / "elsewhere") / "handoff.md"
    paths.ensure_dir(other.parent)
    other.write_text(GOOD_NOTES)
    result = run_cli("handover", "--file", str(other), "--no-snapshot", cwd=repo)
    assert result.returncode == 0, result.stderr
    assert other.read_text() == GOOD_NOTES
    notes = Path(run_cli("notes-path", cwd=repo).stdout.strip())
    notes.write_text(GOOD_NOTES)
    run_cli("handover", "--discard", cwd=repo)
    assert run_cli("handover", "--file", str(notes), "--no-snapshot",
                   cwd=repo).returncode == 0
    assert not notes.exists()


# N-6: an OSError names its path and reason, never its message

def test_unexpected_oserror_names_the_path_and_reason(monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture) -> None:
    from context_vigil import cli

    def boom(_args):  # type: ignore[no-untyped-def]
        raise PermissionError(13, "Permission denied", "/data/root/handoff.md")

    monkeypatch.setattr(cli, "_cmd_status", boom)
    assert cli.main(["status"]) == 1
    err = capsys.readouterr().err
    assert "PermissionError" in err and "Permission denied" in err
    assert "/data/root/handoff.md" in err and len(err.strip().splitlines()) == 1


# N-9: wording, and more credential file names for --inline

def test_foreign_block_note_mentions_a_renamed_stdin_variable() -> None:
    script = Path("/x/sl.sh")
    text = f"input=$(cat)\n{install.SL_START}\nfoo\n{install.SL_END}\n"
    assert "no longer matches the line that reads stdin" in install.foreign_block_note(
        script, text)


@pytest.mark.parametrize("name", ["gh_token", "api-token.txt", ".htpasswd", "site.htpasswd",
                                  ".s3cfg", ".boto", ".my.cnf", "server.ppk"])
def test_more_credential_file_names_are_secret_bearing(iso: Path, name: str) -> None:
    from context_vigil import handover
    assert handover.secret_bearing(iso / name)
