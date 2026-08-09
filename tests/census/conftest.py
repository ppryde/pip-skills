import pytest


@pytest.fixture
def store_file(tmp_path, monkeypatch):
    """Point the census store at an isolated temp path for each test."""
    path = tmp_path / "census" / "status.json"
    monkeypatch.setenv("CENSUS_STORE", str(path))
    return path
