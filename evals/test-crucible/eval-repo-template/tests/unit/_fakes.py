"""Test doubles for the unit suite."""


class FakeLedger:
    """In-memory stand-in for ledgerlite.Ledger.

    Mirrors the real ledger's behaviour by replaying the entry log, which keeps
    the fake obviously-correct-by-construction: there is no second copy of the
    balance that could drift from the entries.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[str, int]] = []

    def post(self, account: str, amount: int) -> int:
        running = 0
        for acct, amt in self._entries:
            if acct == account:
                running += amt
        self._entries.append((account, amount))
        return running + amount

    def balance(self, account: str) -> int:
        total = 0
        for acct, amt in self._entries:
            if acct == account:
                total += amt
        return total

    def entry_count(self) -> int:
        return len(self._entries)
