import os

import pytest

# `scripts` is the shipped package; plugins/census/pyproject.toml puts it on pythonpath.


@pytest.fixture
def store_file(tmp_path, monkeypatch):
    """Point the census store at an isolated temp path for each test."""
    path = tmp_path / "census" / "status.json"
    monkeypatch.setenv("CENSUS_STORE", str(path))
    return path


@pytest.fixture(autouse=True)
def _isolated_account(tmp_path_factory, monkeypatch):
    """Never read the developer's real ~/.claude.json, and never leak a cached
    account between cases."""
    from scripts import store

    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    # nothing the developer exported may steer the drawer, the cache or the side channel
    for name in (
        "CENSUS_STORE", "AGENT_UI_STATUSLINE_CACHE", "CENSUS_STATUSLINE_SEGMENTS", "CENSUS_STATUSLINE_COLOR",
        "CENSUS_STATUSLINE_MASCOT", "CENSUS_STATUSLINE_GIT_TTL", "CLAUDE_COST_BUDGET", "CLAUDE_PROFILE", "NO_COLOR",
    ):
        monkeypatch.delenv(name, raising=False)
    # git sees only the temp repos a test builds: no user or system config, no inherited repo
    # (pytest run from a git hook exports GIT_DIR and friends), and no hook from anywhere
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"):
        monkeypatch.delenv(var, raising=False)
    for var in [v for v in os.environ if v.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", os.devnull)
    reset = getattr(store, "reset_account_cache", None)
    if reset:
        reset()
    yield
    if reset:
        reset()
