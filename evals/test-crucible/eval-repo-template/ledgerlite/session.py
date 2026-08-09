"""Session handling for the API layer."""

import itertools

_counter = itertools.count(1)


class Session:
    def __init__(self, user: str) -> None:
        self.id = next(_counter)
        self.user = user
        self.open = True

    def close(self) -> None:
        self.open = False


class Client:
    """A tiny stand-in for the HTTP client used by the integration tests."""

    def __init__(self, store: dict) -> None:
        self._store = store

    def put(self, key: str, value: object) -> None:
        self._store[key] = value

    def get(self, key: str) -> object:
        return self._store.get(key)

    def keys(self) -> list[str]:
        return sorted(self._store)
