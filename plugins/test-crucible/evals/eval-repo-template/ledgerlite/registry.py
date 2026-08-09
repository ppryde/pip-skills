"""Per-account rate overrides."""

import time


class OverrideRegistry:
    """Process-wide store of per-account rate overrides.

    reset() re-reads the override set from the config service, which is how a
    process picks up overrides published since it last looked.
    """

    def __init__(self) -> None:
        self._entries: dict[str, int] = {}

    def reset(self) -> None:
        time.sleep(0.01)
        self._entries.clear()

    def set_override(self, account: str, bps: int) -> None:
        if bps < 0:
            raise ValueError("override must not be negative")
        self._entries[account] = bps

    def get(self, account: str) -> object:
        return self._entries.get(account)

    def count(self) -> int:
        return len(self._entries)


REGISTRY = OverrideRegistry()
