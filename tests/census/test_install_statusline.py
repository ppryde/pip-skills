"""`census install --statusline` / `census uninstall`: the settings.json contract."""
import json
import os
from pathlib import Path

import pytest

from scripts import cli
from scripts import install as ins
from scripts import store as st

OLD = {"type": "command", "command": "bash ~/.claude/statusline-command.sh", "padding": 2}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    shim = tmp_path / "bin" / "census"
    return {"cfg": cfg, "settings": cfg / "settings.json", "shim": shim, "census": tmp_path / "census"}


def write_settings(env, data):
    env["settings"].write_text(json.dumps(data, indent=2))


def settings(env):
    return json.loads(env["settings"].read_text())


def run(env, *args, yes=True):
    argv = ["install", "--shim", str(env["shim"]), *args] + (["--yes"] if yes else [])
    return cli.main(argv)


def uninstall(env, *args, yes=True):
    return cli.main(["uninstall", "--shim", str(env["shim"]), "--script", str(env["cfg"] / "none.sh"), *args] + (["--yes"] if yes else []))


def test_sets_statusline_when_absent(env, capsys):
    write_settings(env, {"model": "opus", "env": {"A": "1"}})
    assert run(env, "--statusline") == 0
    got = settings(env)
    assert got["statusLine"] == {
        "type": "command",
        "command": f"{env['shim']} statusline",
        "refreshInterval": 60,
    }
    assert got["model"] == "opus" and got["env"] == {"A": "1"}
    assert env["shim"].exists()  # the shim is still installed


def test_dry_run_changes_nothing(env, capsys):
    write_settings(env, {"model": "opus"})
    before = env["settings"].read_text()
    assert run(env, "--statusline", yes=False) == 0
    assert env["settings"].read_text() == before and not env["shim"].exists()
    assert "dry run" in capsys.readouterr().out


def test_skips_the_bash_block_step(env):
    script = env["cfg"] / "statusline-command.sh"
    script.write_text("#!/bin/bash\ninput=$(cat)\n")
    write_settings(env, {})
    assert run(env, "--statusline", "--script", str(script)) == 0
    assert "census: record" not in script.read_text()


def test_plain_install_still_edits_the_script_and_leaves_settings(env):
    script = env["cfg"] / "statusline-command.sh"
    script.write_text("#!/bin/bash\ninput=$(cat)\n")
    write_settings(env, {"model": "opus"})
    assert run(env, "--script", str(script)) == 0
    assert "census: record" in script.read_text()
    assert settings(env) == {"model": "opus"}


@pytest.mark.parametrize("content", [None, "{nope", "[1]"])
def test_unusable_settings_refuse_and_change_nothing(env, content, capsys):
    if content is not None:
        env["settings"].write_text(content)
    assert run(env, "--statusline") == 1
    assert "nothing changed" in capsys.readouterr().out
    assert not env["shim"].exists()
    assert (env["settings"].read_text() == content) if content is not None else not env["settings"].exists()


def test_existing_statusline_refused_without_replace(env, capsys):
    write_settings(env, {"statusLine": OLD})
    assert run(env, "--statusline") == 1
    assert "--replace" in capsys.readouterr().out
    assert settings(env) == {"statusLine": OLD} and not env["shim"].exists()


def test_replace_backs_up_the_old_value_verbatim(env):
    write_settings(env, {"statusLine": OLD, "x": 1})
    assert run(env, "--statusline", "--replace") == 0
    assert json.loads((env["census"] / "statusline.previous.json").read_text()) == OLD
    assert settings(env)["statusLine"]["command"].endswith(" statusline") and settings(env)["x"] == 1


def test_uninstall_restores_the_backup_exactly(env):
    write_settings(env, {"statusLine": OLD, "x": [1, {"y": None}]})
    run(env, "--statusline", "--replace")
    assert uninstall(env) == 0
    assert settings(env) == {"statusLine": OLD, "x": [1, {"y": None}]}
    assert not (env["census"] / "statusline.previous.json").exists()
    assert not env["shim"].exists()


def test_uninstall_removes_the_key_it_added(env):
    write_settings(env, {"model": "opus"})
    run(env, "--statusline")
    uninstall(env)
    assert settings(env) == {"model": "opus"}


def test_uninstall_leaves_a_statusline_the_user_changed_since(env, capsys):
    write_settings(env, {"statusLine": OLD})
    run(env, "--statusline", "--replace")
    mine = {"type": "command", "command": "echo mine"}
    write_settings(env, {"statusLine": mine})
    assert uninstall(env) == 0
    assert settings(env) == {"statusLine": mine}
    assert "left alone" in capsys.readouterr().out
    assert (env["census"] / "statusline.previous.json").exists()  # kept so nothing is lost


def test_uninstall_restore_happens_before_purge(env):
    write_settings(env, {"statusLine": OLD})
    run(env, "--statusline", "--replace")
    st.ingest(json.dumps({"session_id": "s1", "cwd": "/x"}))
    assert uninstall(env, "--purge") == 0
    assert settings(env) == {"statusLine": OLD}
    assert not env["census"].exists()


def test_purge_deletes_the_gitcache_and_state_files(env):
    write_settings(env, {})
    run(env, "--statusline", "--segments", "model")
    (env["census"] / "gitcache").mkdir(exist_ok=True)
    (env["census"] / "gitcache" / "abc.json").write_text("{}")
    uninstall(env, "--purge")
    assert not env["census"].exists()


def test_reinstall_is_idempotent(env, capsys):
    write_settings(env, {"model": "opus"})
    run(env, "--statusline")
    once = env["settings"].read_text()
    capsys.readouterr()
    assert run(env, "--statusline") == 0
    assert env["settings"].read_text() == once and "up to date" in capsys.readouterr().out


def test_reinstall_over_our_own_does_not_clobber_the_backup(env):
    write_settings(env, {"statusLine": OLD})
    run(env, "--statusline", "--replace")
    run(env, "--statusline", "--replace")
    assert json.loads((env["census"] / "statusline.previous.json").read_text()) == OLD


class TestSegments:
    def test_written_to_env_in_the_same_write(self, env):
        write_settings(env, {"env": {"A": "1"}})
        assert run(env, "--statusline", "--segments", "context,cost/model,dir") == 0
        assert settings(env)["env"] == {"A": "1", "CENSUS_STATUSLINE_SEGMENTS": "context,cost/model,dir"}

    def test_env_created_when_missing_and_removed_on_uninstall(self, env):
        write_settings(env, {"model": "opus"})
        run(env, "--statusline", "--segments", "context")
        assert settings(env)["env"] == {"CENSUS_STATUSLINE_SEGMENTS": "context"}
        uninstall(env)
        assert settings(env) == {"model": "opus"}

    def test_uninstall_restores_a_value_that_was_there(self, env):
        write_settings(env, {"env": {"CENSUS_STATUSLINE_SEGMENTS": "dir", "A": "1"}})
        run(env, "--statusline", "--segments", "context")
        uninstall(env)
        assert settings(env)["env"] == {"CENSUS_STATUSLINE_SEGMENTS": "dir", "A": "1"}

    def test_a_key_census_did_not_write_survives_uninstall(self, env):
        write_settings(env, {"env": {"CENSUS_STATUSLINE_SEGMENTS": "dir"}})
        run(env, "--statusline")
        uninstall(env)
        assert settings(env)["env"] == {"CENSUS_STATUSLINE_SEGMENTS": "dir"}

    def test_unknown_names_refused_before_anything_changes(self, env, capsys):
        write_settings(env, {})
        assert run(env, "--statusline", "--segments", "context,bogus") == 1
        assert "bogus" in capsys.readouterr().out
        assert settings(env) == {} and not env["shim"].exists()

    def test_flags_need_statusline(self, env):
        write_settings(env, {})
        assert run(env, "--segments", "context") == 1
        assert run(env, "--replace") == 1


def test_foreign_shim_refused_before_settings_change(env):
    write_settings(env, {})
    env["shim"].parent.mkdir(parents=True)
    env["shim"].write_text("#!/bin/sh\necho mine\n")
    assert run(env, "--statusline") == 1
    assert settings(env) == {}


def test_command_string_per_platform(tmp_path):
    shim, census = tmp_path / "bin" / "census", tmp_path / "census"
    assert ins.statusline_command(shim, census, windows=False) == f"{shim} statusline"
    assert ins.statusline_command(shim, census, windows=True) == f'python "{census / "launcher.py"}" statusline'


def test_command_quotes_a_path_with_spaces(tmp_path):
    shim = tmp_path / "my bin" / "census"
    assert ins.statusline_command(shim, tmp_path / "census", windows=False).startswith("'")


def test_windows_command_is_recognised_as_ours(tmp_path):
    shim, census = tmp_path / "bin" / "census", tmp_path / "census"
    setting = {"type": "command", "command": ins.statusline_command(shim, census, windows=True)}
    assert ins._is_ours(setting, shim, census)
    assert not ins._is_ours({"command": "echo statusline"}, shim, census)


def test_settings_mode_and_symlink_survive_the_write(env, tmp_path):
    real = tmp_path / "real-settings.json"
    real.write_text("{}")
    real.chmod(0o640)
    env["settings"].symlink_to(real)
    run(env, "--statusline")
    assert env["settings"].is_symlink() and "statusLine" in json.loads(real.read_text())
    if os.name == "posix":
        assert (real.stat().st_mode & 0o777) == 0o640


def test_no_stray_temp_files_after_write(env):
    write_settings(env, {})
    run(env, "--statusline")
    assert [p.name for p in env["cfg"].iterdir() if p.name.endswith(".tmp")] == []


def test_default_settings_path_follows_config_dir(env):
    class A:
        settings = None

    assert cli._settings_path(A) == Path(env["cfg"]) / "settings.json"


def test_unreadable_backup_leaves_everything_alone(env, capsys):
    write_settings(env, {"statusLine": OLD})
    run(env, "--statusline", "--replace")
    (env["census"] / "statusline.previous.json").write_text("{corrupt")
    before = env["settings"].read_text()
    assert uninstall(env) == 1  # stopped: nothing else is removed either
    assert env["settings"].read_text() == before
    assert (env["census"] / "statusline.previous.json").read_text() == "{corrupt"
    assert env["shim"].exists()
    assert "unreadable" in capsys.readouterr().out


def test_env_that_is_not_an_object_is_refused(env):
    write_settings(env, {"env": ["x"]})
    assert run(env, "--statusline", "--segments", "context") == 1
    assert settings(env) == {"env": ["x"]} and not env["shim"].exists()


def test_empty_string_prior_segments_is_restored_not_removed(env, capsys):
    write_settings(env, {"env": {"CENSUS_STATUSLINE_SEGMENTS": ""}})
    run(env, "--statusline", "--segments", "context")
    capsys.readouterr()
    uninstall(env, yes=False)
    assert "restore" in capsys.readouterr().out
    uninstall(env)
    assert settings(env)["env"] == {"CENSUS_STATUSLINE_SEGMENTS": ""}


# --- review round 2 ---------------------------------------------------------------


class TestExactOwnership:
    def test_a_path_that_merely_starts_with_ours_is_foreign(self, env, capsys):
        lookalike = {"type": "command", "command": f"{env['shim']}-other statusline"}
        write_settings(env, {"statusLine": lookalike})
        assert run(env, "--statusline") == 1  # needs --replace: it is not ours
        assert settings(env) == {"statusLine": lookalike}

    def test_extra_arguments_are_foreign(self, env):
        extra = {"type": "command", "command": f"{env['shim']} statusline --evil"}
        write_settings(env, {"statusLine": extra})
        assert run(env, "--statusline") == 1

    def test_uninstall_leaves_a_lookalike_alone(self, env):
        write_settings(env, {})
        run(env, "--statusline")
        lookalike = {"type": "command", "command": f"{env['shim']}x statusline"}
        write_settings(env, {"statusLine": lookalike})
        uninstall(env)
        assert settings(env) == {"statusLine": lookalike}

    def test_a_substring_inside_another_command_is_foreign(self, env):
        embedded = {"type": "command", "command": f"echo {env['shim']} statusline"}
        write_settings(env, {"statusLine": embedded})
        assert run(env, "--statusline") == 1


def test_up_to_date_launcher_gets_its_executable_bit_back(env):
    write_settings(env, {})
    run(env, "--statusline")
    env["shim"].chmod(0o644)
    run(env, "--statusline")
    assert os.access(env["shim"], os.X_OK)


class TestPlainInstallerUsesTheChosenShim:
    def test_block_calls_the_selected_launcher(self, env):
        script = env["cfg"] / "statusline-command.sh"
        script.write_text("#!/bin/bash\ninput=$(cat)\n")
        assert run(env, "--script", str(script)) == 0
        assert f"{env['shim']} ingest" in script.read_text()

    def test_the_manual_line_names_it_too(self, env, capsys):
        run(env, "--script", str(env["cfg"] / "missing.sh"))
        assert f"{env['shim']} ingest" in capsys.readouterr().out


class TestUninstallStopsWhenRestoreFails:
    def test_unreadable_settings_with_a_backup_removes_nothing(self, env, capsys):
        write_settings(env, {"statusLine": OLD})
        run(env, "--statusline", "--replace")
        env["settings"].write_text("{broken")
        assert uninstall(env, "--purge") == 1
        assert env["shim"].exists() and (env["census"] / "statusline.previous.json").exists()
        assert "stopped" in capsys.readouterr().out

    def test_a_statusline_the_user_changed_keeps_its_backup_through_a_purge(self, env):
        write_settings(env, {"statusLine": OLD})
        run(env, "--statusline", "--replace")
        write_settings(env, {"statusLine": {"type": "command", "command": "echo mine"}})
        uninstall(env, "--purge")
        assert json.loads((env["census"] / "statusline.previous.json").read_text()) == OLD


class TestWindowsLauncher:
    def make_cli(self, root, version):
        cli_path = root / version / "scripts" / "cli.py"
        cli_path.parent.mkdir(parents=True)
        cli_path.write_text(f"import sys\nprint('v{version}', *sys.argv[1:])\n")
        return cli_path

    def test_install_writes_a_stable_launcher_and_points_at_it(self, env, tmp_path):
        write_settings(env, {})
        cli_path = self.make_cli(tmp_path / "cache", "0.4.0")
        code, _ = ins.install_statusline(
            env["shim"], cli_path, env["settings"], env["census"], False, None, True, windows=True
        )
        assert code == 0
        command = settings(env)["statusLine"]["command"]
        assert command == f'python "{env["census"] / "launcher.py"}" statusline'
        assert str(cli_path) not in command  # a versioned path would die on upgrade

    def test_the_launcher_runs_the_cli_and_follows_an_upgrade(self, env, tmp_path):
        import subprocess
        import sys

        write_settings(env, {})
        root = tmp_path / "cache"
        old = self.make_cli(root, "0.4.0")
        ins.install_statusline(env["shim"], old, env["settings"], env["census"], False, None, True, windows=True)
        launcher = env["census"] / "launcher.py"

        def go():
            done = subprocess.run([sys.executable, str(launcher), "a"], capture_output=True, text=True)
            assert done.returncode == 0 and done.stderr == ""
            return done.stdout.strip()

        assert go() == "v0.4.0 a"
        self.make_cli(root, "0.10.0")
        old.unlink()
        assert go() == "v0.10.0 a"

    def test_the_launcher_is_silent_when_nothing_is_left(self, env, tmp_path):
        import subprocess
        import sys

        write_settings(env, {})
        old = self.make_cli(tmp_path / "cache", "0.4.0")
        ins.install_statusline(env["shim"], old, env["settings"], env["census"], False, None, True, windows=True)
        old.unlink()
        done = subprocess.run([sys.executable, str(env["census"] / "launcher.py")], capture_output=True, text=True)
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""

    def test_uninstall_removes_the_launcher_file(self, env, tmp_path):
        write_settings(env, {})
        cli_path = self.make_cli(tmp_path / "cache", "0.4.0")
        ins.install_statusline(env["shim"], cli_path, env["settings"], env["census"], False, None, True, windows=True)
        # on POSIX the command is the windows form here, which uninstall still recognises as ours
        uninstall(env)
        assert not (env["census"] / "launcher.py").exists() and "statusLine" not in settings(env)


class TestNullStatusLine:
    def test_install_over_an_explicit_null_restores_the_null(self, env):
        write_settings(env, {"statusLine": None, "x": 1})
        assert run(env, "--statusline") == 0
        assert settings(env)["statusLine"]["command"].endswith(" statusline")
        uninstall(env)
        assert settings(env) == {"statusLine": None, "x": 1}


class TestStateFile:
    def test_a_state_file_that_is_not_an_object_is_ignored(self, env):
        write_settings(env, {})
        env["census"].mkdir()
        (env["census"] / "statusline.state.json").write_text("[1, 2]")
        assert run(env, "--statusline", "--segments", "context") == 0
        assert uninstall(env) == 0
        assert settings(env) == {}

    def test_uninstall_survives_a_non_object_state(self, env):
        write_settings(env, {})
        run(env, "--statusline")
        (env["census"] / "statusline.state.json").write_text('"x"')
        assert uninstall(env) == 0


class TestPartialInstall:
    def test_a_shim_failure_rolls_back_settings_and_backup(self, env, monkeypatch):
        write_settings(env, {"statusLine": OLD, "x": 1})
        before = env["settings"].read_text()
        real = ins._install_shim

        def failing(shim, cli, apply):
            if apply:
                raise OSError("disk full")
            return real(shim, cli, apply)

        monkeypatch.setattr(ins, "_install_shim", failing)
        assert run(env, "--statusline", "--replace", "--segments", "context") == 1
        assert env["settings"].read_text() == before
        assert not (env["census"] / "statusline.previous.json").exists()
        assert not (env["census"] / "statusline.state.json").exists()

    @pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions and a non-root user")
    def test_an_unwritable_census_dir_refuses_before_anything_changes(self, env, capsys):
        write_settings(env, {})
        env["census"].mkdir()
        env["census"].chmod(0o500)
        try:
            assert run(env, "--statusline") == 1
        finally:
            env["census"].chmod(0o700)
        assert settings(env) == {} and not env["shim"].exists()
        assert "not writable" in capsys.readouterr().out


class TestPurge:
    def test_only_census_temp_prefixes_are_deleted(self, env):
        env["census"].mkdir()
        (env["census"] / ".user.tmp").write_text("mine")
        (env["census"] / ".cli.path.abc.tmp").write_text("x")
        uninstall(env, "--purge")
        assert (env["census"] / ".user.tmp").read_text() == "mine"
        assert not (env["census"] / ".cli.path.abc.tmp").exists()

    def test_a_shared_store_is_purged_account_scoped(self, env, capsys):
        mine = st.account_info()["key"]
        (env["census"] / "sessions").mkdir(parents=True)
        (env["census"] / "limits").mkdir()
        for name, account in (("mine", mine), ("theirs", "acct-other")):
            (env["census"] / "sessions" / f"{name}.json").write_text(json.dumps({"account": account}))
        (env["census"] / "limits" / f"{mine}.json").write_text("{}")
        (env["census"] / "limits" / "acct-other.json").write_text("{}")
        (env["census"] / "cli.path").write_text("/x/cli.py")
        assert uninstall(env, "--purge") == 0
        left = sorted(str(p.relative_to(env["census"])) for p in env["census"].rglob("*") if p.is_file())
        assert left == ["cli.path", "limits/acct-other.json", "sessions/theirs.json"]
        assert "only this account's" in capsys.readouterr().out

    def test_a_store_with_only_my_records_is_removed_whole(self, env):
        st.ingest(json.dumps({"session_id": "s1", "cwd": "/x"}))
        uninstall(env, "--purge")
        assert not env["census"].exists()


def test_settings_flag_needs_statusline(env):
    write_settings(env, {})
    assert run(env, "--settings", str(env["settings"])) == 1


def test_a_shim_that_turns_foreign_at_apply_time_rolls_everything_back(env, monkeypatch):
    write_settings(env, {"model": "opus"})
    before = env["settings"].read_text()
    real = ins._install_shim

    def late_foreign(shim, cli_path, apply):
        if apply:
            return 1, [f"refused: {shim} exists and is not a census launcher"]
        return real(shim, cli_path, apply)

    monkeypatch.setattr(ins, "_install_shim", late_foreign)
    assert run(env, "--statusline") == 1
    assert env["settings"].read_text() == before and not env["shim"].exists()
