"""The `volumes` key of the shared machine config: load, validate, roundtrip.

`CLAUDE_CONFIG_DIR` is pinned into tmp_path by the autouse fixture in
conftest, so `<tmp>/config/overseer/config.json` is the file every test here
reads and writes — never the developer's real one."""
import json
from pathlib import Path

import pytest
from scripts import store


def _config_path(tmp_path: Path) -> Path:
    return tmp_path / "config" / "overseer" / "config.json"


def _write(tmp_path: Path, payload) -> Path:
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


class TestLoadVolumes:
    def test_no_config_file_means_no_volumes(self):
        assert store.load_volumes() == ([], [])

    def test_a_config_without_the_key_is_backward_compatible(self, tmp_path):
        _write(tmp_path, {"claude_dirs": ["~/.claude-personal"], "path_map": {"/a": "/b"}})
        assert store.load_volumes() == ([], [])

    def test_reads_a_volume_and_defaults_the_claude_dir(self, tmp_path):
        _write(tmp_path, {"volumes": [{"name": "wf-state"},
                                      {"name": "other", "claude_dir": "/home/me/.claude/"}]})
        vols, problems = store.load_volumes()
        assert vols == [store.Volume("wf-state", ".config/claude"),
                        store.Volume("other", "home/me/.claude")]
        assert problems == []

    def test_label_is_a_stable_non_host_path(self):
        assert store.Volume("wf-state").label == "docker://wf-state"
        assert store.is_volume_label("docker://wf-state")
        assert not store.is_volume_label("/home/me/.claude")
        assert not store.is_volume_label(None)

    @pytest.mark.parametrize("entry", [
        "wf-state",                                       # not an object
        {"claude_dir": ".config/claude"},                 # no name
        {"name": 7},                                      # name is not a string
        {"name": "wf state"},                             # space
        {"name": "-rf"},                                  # would be read as a docker option
        {"name": "wf;rm"},
        {"name": "wf", "claude_dir": "../etc"},           # traversal
        {"name": "wf", "claude_dir": "a/../../etc"},
        {"name": "wf", "claude_dir": 'a"; rm -rf /'},     # quote / shell metacharacters
        {"name": "wf", "claude_dir": "-rf"},
        {"name": "wf", "claude_dir": "/"},
        {"name": "wf", "claude_dir": 3},
    ])
    def test_a_bad_entry_is_skipped_and_reported_never_raised(self, tmp_path, entry):
        _write(tmp_path, {"volumes": [entry, {"name": "good"}]})
        vols, problems = store.load_volumes()
        assert [v.name for v in vols] == ["good"]
        assert len(problems) == 1 and "skipped volume entry" in problems[0]

    def test_volumes_not_a_list_is_reported(self, tmp_path):
        _write(tmp_path, {"volumes": {"name": "wf"}})
        vols, problems = store.load_volumes()
        assert vols == [] and problems and "must be a list" in problems[0]

    def test_malformed_json_degrades_to_none(self, tmp_path):
        _write(tmp_path, "{not json")
        assert store.load_volumes() == ([], [])

    def test_duplicate_names_keep_the_first(self, tmp_path):
        _write(tmp_path, {"volumes": [{"name": "wf", "claude_dir": "a"},
                                      {"name": "wf", "claude_dir": "b"}]})
        assert store.volumes() == [store.Volume("wf", "a")]

    def test_volumes_never_leak_into_claude_dirs(self, tmp_path):
        # A volume has no host path: it must not be treated as a config dir
        # (which would make store resolution stat a nonexistent directory).
        _write(tmp_path, {"volumes": [{"name": "wf-state"}]})
        (tmp_path / "config").mkdir(exist_ok=True)
        assert store.claude_dirs() == [tmp_path / "config"]


class TestSaveVolumes:
    def test_roundtrip(self, tmp_path):
        vols = [store.Volume("wf-state"), store.Volume("b", "x/y")]
        store.save_volumes(vols)
        assert store.volumes() == vols

    def test_preserves_every_other_key(self, tmp_path):
        _write(tmp_path, {"claude_dirs": ["/x"], "path_map": {"/a": "/b"}, "central_dir": "/c"})
        store.save_volumes([store.Volume("wf-state")])
        data = json.loads(_config_path(tmp_path).read_text())
        assert data["claude_dirs"] == ["/x"]
        assert data["path_map"] == {"/a": "/b"}
        assert data["central_dir"] == "/c"
        assert data["volumes"] == [{"name": "wf-state", "claude_dir": ".config/claude"}]

    def test_refuses_to_clobber_a_malformed_file(self, tmp_path):
        path = _write(tmp_path, "{not json")
        with pytest.raises(ValueError, match="malformed"):
            store.save_volumes([store.Volume("wf")])
        assert path.read_text() == "{not json"

    def test_leaves_no_tmp_file_behind(self, tmp_path):
        store.save_volumes([store.Volume("wf")])
        assert [p.name for p in _config_path(tmp_path).parent.iterdir()] == ["config.json"]


class TestNormaliseVolume:
    def test_strips_surrounding_slashes(self):
        assert store.normalise_volume("wf", "/.config/claude/").claude_dir == ".config/claude"


class TestParseAccountProfile:
    def test_whitelists_and_matches_the_file_reader(self, tmp_path):
        text = json.dumps({"oauthAccount": {
            "accountUuid": "a-1", "organizationUuid": "o-1", "organizationType": "claude_enterprise",
            "seatTier": "tier", "emailAddress": "x@y.z", "fullName": "N", "organizationName": "Org"}})
        (tmp_path / ".claude.json").write_text(text)
        parsed = store.parse_account_profile(text)
        assert parsed == store.account_profile(tmp_path)
        assert parsed is not None
        assert set(parsed) == {"accountUuid", "organizationUuid", "organizationType", "seatTier"}

    def test_none_for_junk_and_empty_dict_for_api_key(self):
        assert store.parse_account_profile("{oops") is None
        assert store.parse_account_profile("[]") is None
        assert store.parse_account_profile("{}") == {}
        assert store.parse_account_profile("") == {}
