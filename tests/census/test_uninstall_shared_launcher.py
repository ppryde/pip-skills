"""SS-1: the launcher (~/.local/bin/census) is one file for every account. Uninstalling one account while another
account's settings.json still runs it asks (a flag per answer) instead of silently breaking the other account."""
import json

import pytest
from scripts import cli
from scripts import install as ins


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Two accounts under a pinned HOME, both with the census status line installed through one launcher."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    shim = home / ".local" / "bin" / "census"
    cfgs = {}
    for name in (".claude", ".claude-personal"):
        cfg = home / name
        cfg.mkdir()
        (cfg / "settings.json").write_text("{}")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        assert cli.main(["install", "--statusline", "--shim", str(shim), "--yes"]) == 0
        cfgs[name] = cfg
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgs[".claude"]))
    return {"shim": shim, "a": cfgs[".claude"], "b": cfgs[".claude-personal"], "home": home}


def uninstall(env, *args, yes=True):
    argv = ["uninstall", "--shim", str(env["shim"]), "--script", str(env["a"] / "none.sh"), *args]
    return cli.main(argv + (["--yes"] if yes else []))


def statusline(cfg):
    return json.loads((cfg / "settings.json").read_text()).get("statusLine")


def test_other_accounts_using_the_launcher_are_found(two):
    users = ins.other_launcher_users(two["shim"], two["a"])
    assert users == [two["b"]]


def test_an_account_that_does_not_use_it_is_not_listed(two):
    (two["b"] / "settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": "echo hi"}}))
    assert ins.other_launcher_users(two["shim"], two["a"]) == []


def test_without_a_choice_an_apply_changes_nothing_and_says_what_to_pass(two, capsys):
    assert uninstall(two) == 1
    out = capsys.readouterr().out
    assert "--this-account-only" in out and "--all-accounts" in out and str(two["b"]) in out
    assert two["shim"].exists() and statusline(two["a"]) is not None and statusline(two["b"]) is not None


def test_a_dry_run_names_the_choice_and_changes_nothing(two, capsys):
    assert uninstall(two, yes=False) == 0
    out = capsys.readouterr().out
    assert "--all-accounts" in out and str(two["b"]) in out
    assert two["shim"].exists() and statusline(two["a"]) is not None


def test_this_account_only_keeps_the_launcher_for_the_other(two, capsys):
    assert uninstall(two, "--this-account-only") == 0
    assert statusline(two["a"]) is None
    assert two["shim"].exists() and statusline(two["b"]) is not None
    assert "left in place" in capsys.readouterr().out


def test_all_accounts_restores_each_status_line_and_removes_the_launcher(two):
    assert uninstall(two, "--all-accounts") == 0
    assert statusline(two["a"]) is None and statusline(two["b"]) is None
    assert not two["shim"].exists()


def test_all_accounts_never_purges_the_other_accounts_data(two):
    other = two["b"] / "census" / "sessions"
    other.mkdir(parents=True)
    keep = other / "s1.json"
    keep.write_text(json.dumps({"version": 2, "updated_at": 1.0, "payload": {}}))
    assert uninstall(two, "--all-accounts", "--purge") == 0
    assert keep.exists()


def test_the_two_choices_exclude_each_other(two):
    assert uninstall(two, "--all-accounts", "--this-account-only") == 1


def test_with_no_other_account_nothing_changes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cfg = home / ".claude"
    cfg.mkdir()
    (cfg / "settings.json").write_text("{}")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    shim = home / "bin" / "census"
    cli.main(["install", "--statusline", "--shim", str(shim), "--yes"])
    assert cli.main(["uninstall", "--shim", str(shim), "--script", str(cfg / "n.sh"), "--yes"]) == 0
    assert not shim.exists()


def test_data_is_kept_unless_purge_and_the_plan_says_it_cannot_be_recovered(two, capsys):
    (two["a"] / "census").mkdir(exist_ok=True)
    assert uninstall(two, "--this-account-only", yes=False) == 0
    keep = capsys.readouterr().out
    assert "kept" in keep and "--purge" in keep
    assert uninstall(two, "--this-account-only", "--purge", yes=False) == 0
    assert "cannot be recovered" in capsys.readouterr().out
