import pytest


@pytest.fixture
def accounts():
    return ("assets", "liabilities", "equity")
