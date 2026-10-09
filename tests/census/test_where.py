"""`census where`: a read-only report of where census and census-mod are, so a skill needs no shell variable."""
import json
import os
from pathlib import Path

import pytest

from scripts import cli
from scripts import where as wh


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / ".claude-test"
    path.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(path))
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_PLUGIN_DIRS", raising=False)
    return path


def install(cfg, marketplace, plugin, version, orphaned=False, cli_py=True):
    root = cfg / "plugins" / "cache" / marketplace / plugin / version
    marker = root / ("hooks/hooks.json" if plugin == "census-mod" else "scripts/cli.py")
    marker.parent.mkdir(parents=True)
    if cli_py:
        marker.write_text("")
    if orphaned:
        (root / ".orphaned_at").write_text("1")
    return root


def settings(cfg, data):
    (cfg / "settings.json").write_text(json.dumps(data) if not isinstance(data, str) else data)


class TestReport:
    def test_the_config_dir_and_census_dir_are_resolved_for_you(self, cfg):
        out = wh.report()
        assert out["config_dir"] == str(cfg)
        assert out["census_dir"] == str(cfg / "census")
        assert out["settings_path"] == str(cfg / "settings.json")

    def test_census_store_moves_the_census_dir(self, cfg, monkeypatch, tmp_path):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "elsewhere"))
        assert wh.report()["census_dir"] == str(tmp_path / "elsewhere")

    def test_this_plugins_own_root(self, cfg):
        assert Path(wh.report()["plugin_root"]) == Path(wh.__file__).resolve().parents[1]

    def test_census_installs_in_the_plugin_cache_with_orphans_marked(self, cfg):
        install(cfg, "pip-skills", "census", "0.6.2")
        install(cfg, "wf-claude-market", "census", "0.6.1", orphaned=True)
        install(cfg, "pip-skills", "census", "0.0.1", cli_py=False)  # no CLI in it: not an install
        found = {(i["marketplace"], i["version"]): i["orphaned"] for i in wh.report()["census_installs"]}
        assert found == {("pip-skills", "0.6.2"): False, ("wf-claude-market", "0.6.1"): True}

    def test_no_cache_is_an_empty_list(self, cfg):
        assert wh.report()["census_installs"] == []

    def test_enabled_plugins_and_the_status_line_come_from_settings(self, cfg):
        settings(cfg, {
            "enabledPlugins": {"census@pip-skills": True, "census@wf-claude-market": False, "census-mod@pip-skills": True, "other@x": True},
            "statusLine": {"type": "command", "command": "bash ~/.claude/line.sh"},
        })
        out = wh.report()
        assert out["enabled_census"] == {"census@pip-skills": True, "census@wf-claude-market": False}
        assert out["status_line"] == "bash ~/.claude/line.sh"
        assert out["settings_exists"] is True and out["settings_valid"] is True

    def test_census_mod_installed_and_enabled(self, cfg):
        install(cfg, "pip-skills", "census-mod", "0.3.1")
        settings(cfg, {"enabledPlugins": {"census-mod@pip-skills": True}})
        mod = wh.report()["census_mod"]
        assert mod == {"installed": True, "enabled": True, "via_plugin_dir": False, "installs": ["pip-skills 0.3.1"]}

    def test_census_mod_installed_but_disabled(self, cfg):
        install(cfg, "pip-skills", "census-mod", "0.3.1")
        settings(cfg, {"enabledPlugins": {"census-mod@pip-skills": False}})
        mod = wh.report()["census_mod"]
        assert mod["installed"] is True and mod["enabled"] is False

    def test_census_mod_loaded_from_a_plugin_dir(self, cfg, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_DIRS", "/src/pip-skills/plugins/census-mod/plugin")
        mod = wh.report()["census_mod"]
        assert mod["via_plugin_dir"] is True and mod["enabled"] is True

    def test_plugin_dirs_can_be_set_in_settings_env(self, cfg):
        settings(cfg, {"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/census-mod/plugin:/y"}})
        assert wh.report()["census_mod"]["via_plugin_dir"] is True

    def test_not_installed_at_all(self, cfg):
        mod = wh.report()["census_mod"]
        assert mod == {"installed": False, "enabled": False, "via_plugin_dir": False, "installs": []}

    def test_no_settings_file(self, cfg):
        out = wh.report()
        assert out["settings_exists"] is False and out["settings_valid"] is None and out["status_line"] is None

    @pytest.mark.parametrize("junk", ["{ nope", "[]", "42", '"x"'])
    def test_settings_that_are_not_an_object_never_raise(self, cfg, junk):
        settings(cfg, junk)
        out = wh.report()
        assert out["settings_exists"] is True and out["settings_valid"] is False
        assert out["status_line"] is None and out["enabled_census"] == {}

    def test_a_status_line_that_is_not_a_command_object(self, cfg):
        settings(cfg, {"statusLine": "str", "enabledPlugins": ["x"]})
        out = wh.report()
        assert out["status_line"] is None and out["enabled_census"] == {}


class TestCommand:
    def test_prints_one_json_object_and_exits_zero(self, cfg, capsys):
        assert cli.main(["where"]) == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["config_dir"] == str(cfg)

    def test_is_read_only(self, cfg, tmp_path):
        before = sorted(str(p) for p in tmp_path.rglob("*"))
        cli.main(["where"])
        assert sorted(str(p) for p in tmp_path.rglob("*")) == before


class TestConfigDirFlag:
    """--config-dir DIR overrides CLAUDE_CONFIG_DIR for that run only, on install, uninstall and where."""

    def other(self, tmp_path):
        path = tmp_path / ".claude-other"
        path.mkdir()
        (path / "settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": "mine.sh"}}))
        return path

    def test_where_reports_the_dir_it_was_given(self, cfg, tmp_path, capsys):
        other = self.other(tmp_path)
        assert cli.main(["where", "--config-dir", str(other)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["config_dir"] == str(other) and out["status_line"] == "mine.sh"
        assert out["census_dir"] == str(other / "census")

    def test_the_environment_is_restored_afterwards(self, cfg, tmp_path):
        cli.main(["where", "--config-dir", str(self.other(tmp_path))])
        assert os.environ["CLAUDE_CONFIG_DIR"] == str(cfg)

    def test_unset_environment_stays_unset(self, cfg, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CONFIG_DIR")
        cli.main(["where", "--config-dir", str(self.other(tmp_path))])
        assert "CLAUDE_CONFIG_DIR" not in os.environ

    def test_install_dry_run_names_the_account_on_its_first_line(self, cfg, tmp_path, capsys):
        other = self.other(tmp_path)
        shim = tmp_path / "bin" / "census"
        assert cli.main(["install", "--statusline", "--replace", "--shim", str(shim), "--config-dir", str(other)]) == 0
        first = capsys.readouterr().out.splitlines()[0]
        assert first == f"config dir: {other}"
        assert json.loads((other / "settings.json").read_text())["statusLine"]["command"] == "mine.sh"  # a dry run changes nothing

    def test_install_applies_to_the_given_dir_not_the_environments(self, cfg, tmp_path):
        other = self.other(tmp_path)
        shim = tmp_path / "bin" / "census"
        assert cli.main(["install", "--statusline", "--replace", "--yes", "--shim", str(shim), "--config-dir", str(other)]) == 0
        assert "census" in json.loads((other / "settings.json").read_text())["statusLine"]["command"]
        assert not (cfg / "settings.json").exists()
        assert (other / "census" / "statusline.previous.json").exists()

    def test_uninstall_dry_run_names_the_account_too(self, cfg, tmp_path, capsys):
        other = self.other(tmp_path)
        assert cli.main(["uninstall", "--shim", str(tmp_path / "bin" / "census"), "--config-dir", str(other)]) == 0
        assert capsys.readouterr().out.splitlines()[0] == f"config dir: {other}"

    def test_without_the_flag_nothing_changes_for_existing_callers(self, cfg, tmp_path, capsys):
        assert cli.main(["uninstall", "--shim", str(tmp_path / "bin" / "census")]) == 0
        assert capsys.readouterr().out.splitlines()[0] == f"config dir: {cfg}"  # a dry run always says which account

    def test_the_flag_is_not_offered_elsewhere(self, cfg, capsys):
        assert cli.main(["read", "--config-dir", "/x"]) == 1


class TestReviewRound:
    def test_settings_that_are_not_utf8_are_invalid_not_a_crash(self, cfg):
        (cfg / "settings.json").write_bytes(b'{"statusLine": "\xff\xfe"}')
        out = wh.report()
        assert out["settings_exists"] is True and out["settings_valid"] is False
        assert out["status_line"] is None

    @pytest.mark.parametrize("dirs,expected", [
        ("/src/pip-skills/plugins/census-mod/plugin", True),
        ("/src/census-mod", True),
        ("/a:/b/census-mod/plugin", True),
        ("C:\\src\\census-mod\\plugin;D:\\x", True),
        ("/tmp/census-mod-backup/plugin", False),
        ("/tmp/not-census-mod/plugin", False),
        ("/tmp/census-mod.old", False),
        ("", False),
    ])
    def test_a_plugin_dir_names_census_mod_only_as_a_whole_path_component(self, cfg, monkeypatch, dirs, expected):
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_DIRS", dirs)
        assert wh.report()["census_mod"]["via_plugin_dir"] is expected
        assert wh.report()["census_mod"]["enabled"] is expected


class TestVitalsFlag:
    def test_where_says_whether_this_census_ships_vitals(self, cfg):
        assert wh.report()["vitals"] is (Path(wh.__file__).resolve().parent / "vitals.py").is_file() is True

    def test_it_is_false_when_vitals_py_is_absent(self, cfg, monkeypatch, tmp_path):
        fake = tmp_path / "scripts"
        fake.mkdir()
        monkeypatch.setattr(wh, "__file__", str(fake / "where.py"))
        assert wh.report()["vitals"] is False
