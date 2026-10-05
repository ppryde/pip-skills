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
