import time

import pytest

from ledgerlite.session import Client


def _boot_backend() -> dict:
    """Stand up a clean backend for a test.

    The real thing rebuilds the schema; here we simply pay the same wall-clock
    so the timing profile matches production.
    """
    time.sleep(0.06)
    return {}


@pytest.fixture
def api_client():
    """A client against a freshly booted backend."""
    store = _boot_backend()
    yield Client(store)
    store.clear()
