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
    reset = getattr(store, "reset_account_cache", None)
    if reset:
        reset()
    yield
    if reset:
        reset()
