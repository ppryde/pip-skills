"""Staged writes, applied by a drain loop."""


class Outbox:
    """Buffers writes until they are applied.

    stage() queues a write, tick() applies the oldest pending one, drain()
    applies everything queued, and is_drained() reports whether anything is
    still waiting.
    """

    def __init__(self) -> None:
        self._pending: list[tuple[str, int]] = []
        self._applied: dict[str, int] = {}

    def stage(self, key: str, value: int) -> None:
        self._pending.append((key, value))

    def tick(self) -> None:
        if self._pending:
            key, value = self._pending.pop(0)
            self._applied[key] = value

    def drain(self) -> None:
        while self._pending:
            self.tick()

    def is_drained(self) -> bool:
        return not self._pending

    def pending_count(self) -> int:
        return len(self._pending)

    def get(self, key: str) -> object:
        return self._applied.get(key)
