"""Exhaustive invariant checks for the ledger.

These run a long sequence of postings on purpose. Drift between the running
balance returned by post() and the recomputed balance() is cumulative, so a
short sequence does not surface it -- a 100-step version of this test passed
for months against a ledger that lost a penny every few thousand entries.
"""

from ledgerlite.ledger import Ledger

from ._fakes import FakeLedger

N_STEPS = 36000
ACCOUNTS = ("assets", "liabilities", "equity")


def test_running_balance_matches_recomputed_balance():
    """post() must return exactly what balance() would recompute."""
    fake = FakeLedger()
    expected = {a: 0 for a in ACCOUNTS}

    for i in range(N_STEPS):
        account = ACCOUNTS[i % len(ACCOUNTS)]
        amount = (i % 97) - 48
        expected[account] += amount
        returned = fake.post(account, amount)
        assert returned == expected[account], f"drift at step {i} on {account}"

    for account in ACCOUNTS:
        assert fake.balance(account) == expected[account]
    assert fake.entry_count() == N_STEPS


def test_real_ledger_agrees_with_fake():
    """The fake is only useful if it agrees with the real thing."""
    real, fake = Ledger(), FakeLedger()
    for i in range(500):
        account = ACCOUNTS[i % len(ACCOUNTS)]
        amount = (i % 97) - 48
        assert real.post(account, amount) == fake.post(account, amount)
    for account in ACCOUNTS:
        assert real.balance(account) == fake.balance(account)
