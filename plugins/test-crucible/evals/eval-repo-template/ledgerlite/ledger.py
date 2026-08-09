"""Double-entry ledger core."""


class Ledger:
    """Tracks per-account balances. Balances are maintained incrementally."""

    def __init__(self) -> None:
        self._balances: dict[str, int] = {}
        self._entries: list[tuple[str, int]] = []

    def post(self, account: str, amount: int) -> int:
        """Post `amount` to `account` and return the new running balance."""
        new = self._balances.get(account, 0) + amount
        self._balances[account] = new
        self._entries.append((account, amount))
        return new

    def balance(self, account: str) -> int:
        return self._balances.get(account, 0)

    def entry_count(self) -> int:
        return len(self._entries)
