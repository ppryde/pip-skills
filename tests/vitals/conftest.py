import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Never read the developer's real census store, config dir or session:
    every source vitals consults is pinned inside tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    monkeypatch.setenv("CENSUS_CLI", str(tmp_path / "no-census.py"))
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    # git must see only the temp repos the tests build: no user/system config,
    # no inherited repo (pytest run from a git hook exports GIT_DIR & co).
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG"):
        monkeypatch.delenv(var, raising=False)
