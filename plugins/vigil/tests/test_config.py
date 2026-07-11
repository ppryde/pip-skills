import pytest

from scripts.config import (
    DEFAULTS,
    ConfigError,
    config_path,
    get_config,
    load_config,
    set_config,
)
from scripts.store import ensure_root


class TestDefaults:
    def test_load_on_empty_repo_returns_defaults(self, tmp_path):
        ensure_root(tmp_path)
        assert load_config(tmp_path) == DEFAULTS

    def test_get_falls_back_to_default(self, tmp_path):
        ensure_root(tmp_path)
        assert get_config(tmp_path, "context.threshold") == 35
        assert get_config(tmp_path, "context.mode") == "local"


class TestSetAndGet:
    def test_set_threshold_coerces_int(self, tmp_path):
        ensure_root(tmp_path)
        assert set_config(tmp_path, "context.threshold", "40") == 40
        assert get_config(tmp_path, "context.threshold") == 40
        assert config_path(tmp_path).exists()

    def test_set_mode_remote_accepted(self, tmp_path):
        ensure_root(tmp_path)
        assert set_config(tmp_path, "context.mode", "remote") == "remote"

    @pytest.mark.parametrize("key,value", [
        pytest.param("context.mode", "nonsense", id="bad-mode"),
        pytest.param("context.bogus", "1", id="unknown-key"),
        pytest.param("context.threshold", "150", id="threshold-above-max"),
        pytest.param("context.threshold", "0", id="threshold-below-min"),
        pytest.param("context.window", "0", id="window-non-positive"),
    ])
    def test_invalid_set_rejected(self, tmp_path, key, value):
        ensure_root(tmp_path)
        with pytest.raises(ConfigError):
            set_config(tmp_path, key, value)


class TestCorruptFile:
    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        ensure_root(tmp_path)
        config_path(tmp_path).write_text("{ not json")
        assert load_config(tmp_path) == DEFAULTS


class TestPath:
    def test_config_lives_under_dot_vigil(self, tmp_path):
        ensure_root(tmp_path)
        assert config_path(tmp_path) == tmp_path / ".vigil" / "config.json"
