import json
import os

import pytest

from scripts import config, paths


def _write_config(payload) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


class TestLoadSources:
    def test_missing_file_is_no_sources_not_an_error(self):
        assert config.load_sources() == []

    def test_parses_known_keys_and_keeps_the_rest_as_options(self):
        _write_config({"sources": [
            {"type": "notion", "via": "api", "label": "notion", "context": "work",
             "me": "rhona@example.com"},
        ]})
        [src] = config.load_sources()
        assert (src.type, src.via, src.label, src.context) == ("notion", "api", "notion", "work")
        assert src.options == {"me": "rhona@example.com"}

    @pytest.mark.parametrize("entry, needle", [
        ({"via": "api", "label": "n", "context": "work"}, "type"),
        ({"type": "notion", "via": "api", "label": "../etc", "context": "work"}, "label"),
        ({"type": "notion", "via": "api", "label": "n", "context": "wo rk"}, "context"),
    ])
    def test_rejects_bad_entries_by_naming_the_field(self, entry, needle):
        _write_config({"sources": [entry]})
        with pytest.raises(config.ConfigError, match=needle):
            config.load_sources()

    def test_rejects_duplicate_labels(self):
        entry = {"type": "notion", "via": "api", "label": "n", "context": "work"}
        _write_config({"sources": [entry, entry]})
        with pytest.raises(config.ConfigError, match="duplicate"):
            config.load_sources()

    def test_malformed_json_is_a_config_error(self):
        path = paths.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{nope")
        with pytest.raises(config.ConfigError, match="config"):
            config.load_sources()


class TestSecrets:
    def test_missing_secret_is_none(self):
        assert config.read_secret("notion") is None
        assert config.secret_is_private("notion") is False

    def test_reads_and_strips_a_private_secret(self):
        path = paths.secret_path("notion")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ntn_invented_token\n")
        os.chmod(path, 0o600)
        assert config.read_secret("notion") == "ntn_invented_token"
        assert config.secret_is_private("notion") is True

    def test_world_readable_secret_is_flagged(self):
        path = paths.secret_path("notion")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ntn_invented_token")
        os.chmod(path, 0o644)
        assert config.secret_is_private("notion") is False
