import pytest

from scripts.store import ensure_root


@pytest.fixture
def repo(tmp_path):
    ensure_root(tmp_path)
    return tmp_path
