import pytest


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
    reset = getattr(store, "reset_account_cache", None)
    if reset:
        reset()
    yield
    if reset:
        reset()
