"""The `remotes` key of the shared machine config: load, validate, roundtrip.
Mirrors `test_volumes_config.py` — same file, same isolation, a sibling key."""
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


class TestLoadRemotes:
    def test_no_config_file_means_no_remotes(self):
        assert store.load_remotes() == ([], [])

    def test_a_config_without_the_key_is_backward_compatible(self, tmp_path):
        _write(tmp_path, {"claude_dirs": ["~/.claude-personal"], "volumes": []})
        assert store.load_remotes() == ([], [])

    def test_reads_a_remote_and_defaults_everything_but_name_and_host(self, tmp_path):
        _write(tmp_path, {"remotes": [{"name": "prod-access-env", "host": "prod-access-env.wayflyer.team"}]})
        rems, problems = store.load_remotes()
        assert rems == [store.Remote("prod-access-env", "prod-access-env.wayflyer.team",
                                     store.DEFAULT_REMOTE_CLAUDE_DIR, "minimal", None, 900, True)]
        assert problems == []

    def test_label_is_a_stable_non_host_path(self):
        remote = store.normalise_remote("prod-access-env", "prod-access-env.wayflyer.team")
        assert remote.label == "remote://prod-access-env"
        assert store.is_remote_label(remote.label)
        assert not store.is_remote_label("/Users/me/.claude")
        assert not store.is_remote_label("docker://wf-state")
        assert not store.is_remote_label(None)

    def test_mirror_root_defaults_under_the_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
        remote = store.normalise_remote("prod-access-env", "prod-access-env.wayflyer.team")
        assert remote.mirror_root() == tmp_path / "config" / "chronicle" / "remotes" / "prod-access-env"

    def test_mirror_dir_overrides_the_default(self, tmp_path):
        remote = store.normalise_remote("p1", "h1", mirror_dir=str(tmp_path / "archive"))
        assert remote.mirror_root() == tmp_path / "archive"

    def test_interval_is_clamped_to_the_minimum(self):
        assert store.normalise_remote("p1", "h1", interval_s=5).interval_s == store.MIN_REMOTE_INTERVAL_S
        assert store.normalise_remote("p1", "h1", interval_s=3600).interval_s == 3600

    def test_duplicate_names_keep_the_first(self, tmp_path):
        _write(tmp_path, {"remotes": [{"name": "p1", "host": "h1"}, {"name": "p1", "host": "h2"}]})
        rems, _ = store.load_remotes()
        assert [r.host for r in rems] == ["h1"]

    @pytest.mark.parametrize(("name", "host", "kw", "message"), [
        ("p1 space", "h1", {}, "invalid remote name"),
        ("-p1", "h1", {}, "invalid remote name"),
        ("p1;rm -rf /", "h1", {}, "invalid remote name"),
        ("p1", "h1 space", {}, "invalid remote host"),
        ("p1", "-oProxyCommand=x", {}, "invalid remote host"),
        ("p1", "h1;rm -rf /", {}, "invalid remote host"),
        ("p1", "h1", {"claude_dir": "relative/path"}, "invalid claude dir"),
        ("p1", "h1", {"claude_dir": "/a/../../etc"}, "invalid claude dir"),
        ("p1", "h1", {"claude_dir": '/a"; rm -rf /'}, "invalid claude dir"),
        ("p1", "h1", {"fidelity": "everything"}, "invalid fidelity"),
        ("p1", "h1", {"interval_s": "soon"}, "invalid interval_s"),
        ("p1", "h1", {"interval_s": True}, "invalid interval_s"),
    ])
    def test_injection_shaped_or_malformed_values_are_refused(self, name, host, kw, message):
        with pytest.raises(ValueError, match=message):
            store.normalise_remote(name, host, **kw)

    def test_add_never_connects_is_just_validation(self):
        # normalise_remote is pure: no subprocess/socket import happens here.
        store.normalise_remote("prod-access-env", "prod-access-env.wayflyer.team",
                               claude_dir="/opt/wf-state/.config/claude", fidelity="attribution",
                               mirror_dir="~/archive", interval_s=1800, enabled=False)

    def test_a_bad_entry_is_reported_but_does_not_stop_the_good_ones(self, tmp_path):
        _write(tmp_path, {"remotes": [{"name": "-bad", "host": "h1"}, {"name": "p1", "host": "h1"}]})
        rems, problems = store.load_remotes()
        assert [r.name for r in rems] == ["p1"]
        assert len(problems) == 1 and "bad" in problems[0]

    def test_remotes_key_must_be_a_list(self, tmp_path):
        _write(tmp_path, {"remotes": "nope"})
        rems, problems = store.load_remotes()
        assert rems == [] and problems


class TestSaveRemotes:
    def test_roundtrip_preserves_every_other_key(self, tmp_path):
        _write(tmp_path, {"claude_dirs": ["~/.claude-personal"],
                          "volumes": [{"name": "wf-state"}], "path_map": {"/a": "/b"}})
        remote = store.normalise_remote("prod-access-env", "prod-access-env.wayflyer.team")
        store.save_remotes([remote])
        saved = json.loads(_config_path(tmp_path).read_text())
        assert saved["claude_dirs"] == ["~/.claude-personal"]
        assert saved["volumes"] == [{"name": "wf-state"}]
        assert saved["path_map"] == {"/a": "/b"}
        assert saved["remotes"] == [{
            "name": "prod-access-env", "host": "prod-access-env.wayflyer.team",
            "claude_dir": store.DEFAULT_REMOTE_CLAUDE_DIR, "fidelity": "minimal",
            "mirror_dir": None, "interval_s": 900, "enabled": True,
        }]
        rems, problems = store.load_remotes()
        assert rems == [remote] and problems == []

    def test_malformed_existing_config_raises_rather_than_overwriting(self, tmp_path):
        _write(tmp_path, "{not json")
        with pytest.raises(ValueError, match="malformed config JSON"):
            store.save_remotes([])


class TestRemoteMirrorDirFor:
    def test_resolves_a_configured_label(self, tmp_path):
        _write(tmp_path, {"remotes": [{"name": "p1", "host": "h1", "mirror_dir": str(tmp_path / "m")}]})
        assert store.remote_mirror_dir_for("remote://p1") == tmp_path / "m"

    def test_none_for_an_unconfigured_or_non_remote_label(self, tmp_path):
        _write(tmp_path, {"remotes": [{"name": "p1", "host": "h1"}]})
        assert store.remote_mirror_dir_for("remote://gone") is None
        assert store.remote_mirror_dir_for("/Users/me/.claude") is None
        assert store.remote_mirror_dir_for(None) is None
