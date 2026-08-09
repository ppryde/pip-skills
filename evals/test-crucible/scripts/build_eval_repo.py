#!/usr/bin/env python3
"""Build the synthetic 'ledgerlite' repo used to evaluate the test-suite-health skill.

Ground truth (do NOT put this file inside the generated repo):

  PLANT 1  tests/unit/test_invariants.py + tests/unit/_fakes.py
           One ~6s test. 95%+ of the cost is an O(n^2) linear rescan inside
           FakeLedger.post (test infrastructure), NOT the code under test.
           Tempting-but-wrong fix: lower N_STEPS (weakens the proof).
           Correct fix: keep a running-total dict in the fake.
           Lives in tests/unit/, i.e. OUTSIDE the directory eval-0 names.

  PLANT 2  tests/integration/conftest.py :: api_client
           Flat ~60ms of setup on every integration test (39 of them, ~2.4s).
           Uniform tax, not a hotspot: p50 ~= p99.
           Correct fix: session-scope the boot, keep per-test isolation.

  PLANT 3  tests/integration/test_legacy.py
           12 tests silently skipped by a platform guard that is true everywhere.
           The suite is already not running what it appears to run.

  PLANT 4  tests/integration/test_session_{a..f}.py
           Six files each redefining identical two_sessions / setup_session /
           race_ids fixtures. Hoist candidate. (dryness)

  PLANT 5  tests/unit/test_rates.py
           Ten hand-written near-identical tests that should be one
           parametrize. (dryness)

  PLANT 6  tests/integration/_waiting.py + test_outbox.py      [added iter 2]
           wait_until_drained() sleeps BEFORE checking, so 14 tests that call
           it on an already-drained outbox each pay one full POLL_INTERVAL
           (~50ms) for nothing. ~0.7s.
           Correct fix: check first, sleep only if still pending.
           Tempting-but-wrong: shrink POLL_INTERVAL. Looks like a 10x win, the
           ordering bug survives (still >=1 sleep in the best case), AND it
           silently divides the worst-case timeout budget
           (POLL_INTERVAL * MAX_POLLS, currently 2.0s) by the same factor
           unless MAX_POLLS is raised to compensate -> flakier on a loaded box.
           Graded by scripts/poll_probe.py: monkeypatch time.sleep, call the
           helper on an already-drained outbox, assert ZERO sleeps. A correct
           fix scores 0 whatever the interval; an interval-shrink always
           scores >=1. Plus assert POLL_INTERVAL * MAX_POLLS >= 2.0.

  PLANT 7  ledgerlite/registry.py + tests/unit/test_overrides.py  [added iter 2]
           An autouse fixture calls REGISTRY.reset() (~10ms) before EVERY test
           in the file, including the 14 that never touch the registry. ~0.16s.
           Deliberately the same SHAPE as PLANT 2 (flat per-test fixture tax)
           with the OPPOSITE correct answer, to separate reasoning from
           pattern-matching a previous fix.
           Correct fix: narrow APPLICABILITY -- drop autouse, let only the two
           registry tests request it. Tax falls to ~2x10ms.
           Tempting-but-wrong: widen SCOPE to module/session, which is the
           right answer for PLANT 2. Tax falls to ~1x10ms (an even better
           number) but reset() then runs once and test_override_does_not_leak
           fails, because "assets" survives from the previous test.
           NOTE: that wrong fix is LOUD -- it turns the suite red, so any run
           that verifies will catch it. Its real discrimination is between
           "found the narrowing fix" (~30ms) and "left the tax alone" (~160ms).
           M7 backstops the third bad option: deleting the leak test to get green.

Over-signposting rule for PLANTS 6 and 7: every docstring below is purely
DESCRIPTIVE. None of them warns against the wrong fix. PLANT 1 failed to
discriminate in iteration 1 precisely because test_invariants.py's docstring
argues against shortening N_STEPS, handing the answer to any careful reader.
"""

import os
import shutil
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ledgerlite"

FILES = {}

# ---------------------------------------------------------------- package ---

FILES["pytest.ini"] = """[pytest]
testpaths = tests
python_files = test_*.py
"""

# Without this, running pytest (or any probe that imports a module) leaves
# __pycache__ in the tree. setup_runs*.sh does `git add -A`, so the bytecode
# gets COMMITTED into the baseline and then shows as a modification the moment
# anything runs -- polluting the `git diff` that grading reads.
FILES[".gitignore"] = """__pycache__/
*.py[cod]
.pytest_cache/
"""

FILES["README.md"] = """# ledgerlite

A small double-entry ledger. Tests live in `tests/unit` and `tests/integration`.

    pytest -q
"""

FILES["ledgerlite/__init__.py"] = ""

FILES["ledgerlite/ledger.py"] = '''"""Double-entry ledger core."""


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
'''

FILES["ledgerlite/rates.py"] = '''"""Interest rate arithmetic."""

from decimal import Decimal

BASIS = Decimal("10000")


def annual_to_daily(annual_bps: int) -> Decimal:
    """Convert an annual rate in basis points to a daily fraction."""
    if annual_bps < 0:
        raise ValueError("rate must not be negative")
    return (Decimal(annual_bps) / BASIS) / Decimal(365)


def accrue(principal: int, annual_bps: int, days: int) -> Decimal:
    if days < 0:
        raise ValueError("days must not be negative")
    return Decimal(principal) * annual_to_daily(annual_bps) * Decimal(days)
'''

FILES["ledgerlite/session.py"] = '''"""Session handling for the API layer."""

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
'''

# ------------------------------------------------------------------- PLANT 1

FILES["tests/unit/_fakes.py"] = '''"""Test doubles for the unit suite."""


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
'''

FILES["tests/unit/test_invariants.py"] = '''"""Exhaustive invariant checks for the ledger.

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
'''

# ------------------------------------------------------------------- PLANT 5

_RATE_CASES = [
    ("zero_rate", 0, 0),
    ("one_bp", 1, 1),
    ("fifty_bps", 50, 50),
    ("one_hundred_bps", 100, 100),
    ("five_hundred_bps", 500, 500),
    ("one_thousand_bps", 1000, 1000),
    ("two_thousand_bps", 2000, 2000),
    ("five_thousand_bps", 5000, 5000),
    ("ten_thousand_bps", 10000, 10000),
    ("max_bps", 99999, 99999),
]

_rates = ['''"""Rate conversion tests."""

from decimal import Decimal

import pytest

from ledgerlite.rates import BASIS, accrue, annual_to_daily
''']
for _name, _bps, _ in _RATE_CASES:
    _rates.append(f'''
def test_annual_to_daily_{_name}():
    result = annual_to_daily({_bps})
    assert result == (Decimal({_bps}) / BASIS) / Decimal(365)
    assert result >= 0
''')
_rates.append('''
def test_negative_rate_rejected():
    with pytest.raises(ValueError):
        annual_to_daily(-1)


def test_negative_days_rejected():
    with pytest.raises(ValueError):
        accrue(1000, 500, -1)
''')
FILES["tests/unit/test_rates.py"] = "".join(_rates)

# ------------------------------------------------------------ normal tests --

_ledger_tests = ['''"""Ledger behaviour."""

from ledgerlite.ledger import Ledger
''']
for _i in range(14):
    _ledger_tests.append(f'''
def test_post_and_balance_case_{_i}():
    ledger = Ledger()
    assert ledger.post("assets", {_i * 3}) == {_i * 3}
    assert ledger.balance("assets") == {_i * 3}
    assert ledger.entry_count() == 1
''')
FILES["tests/unit/test_ledger.py"] = "".join(_ledger_tests)

FILES["tests/unit/__init__.py"] = ""
FILES["tests/__init__.py"] = ""
FILES["tests/conftest.py"] = '''import pytest


@pytest.fixture
def accounts():
    return ("assets", "liabilities", "equity")
'''

# ------------------------------------------------------------------- PLANT 2

FILES["tests/integration/conftest.py"] = '''import time

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
'''

FILES["tests/integration/__init__.py"] = ""

for _mod, _n in (("accounts", 13), ("transfers", 13), ("reports", 13)):
    _body = [f'''"""Integration tests for the {_mod} endpoints."""
''']
    for _i in range(_n):
        _body.append(f'''
def test_{_mod}_roundtrip_{_i}(api_client):
    api_client.put("{_mod}-{_i}", {_i})
    assert api_client.get("{_mod}-{_i}") == {_i}
    assert api_client.keys() == ["{_mod}-{_i}"]
''')
    FILES[f"tests/integration/test_api_{_mod}.py"] = "".join(_body)

# ------------------------------------------------------------------- PLANT 3

_legacy = ['''"""Legacy endpoint tests.

Kept for the v1 API, which is still deployed to two customers.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)
''']
for _i in range(12):
    _legacy.append(f'''
def test_legacy_v1_endpoint_{_i}(api_client):
    api_client.put("legacy-{_i}", {_i})
    assert api_client.get("legacy-{_i}") == {_i}
''')
FILES["tests/integration/test_legacy.py"] = "".join(_legacy)

# ------------------------------------------------------------------- PLANT 4

_SESSION_FIXTURES = '''import pytest

from ledgerlite.session import Session


@pytest.fixture
def setup_session():
    def _make(user):
        session = Session(user)
        assert session.open
        return session

    return _make


@pytest.fixture
def two_sessions(setup_session):
    first = setup_session("alice")
    second = setup_session("bob")
    yield first, second
    first.close()
    second.close()


@pytest.fixture
def race_ids(two_sessions):
    first, second = two_sessions
    return sorted((first.id, second.id))
'''

for _letter in "abcdef":
    _body = [f'"""Concurrent session behaviour, group {_letter}."""\n\n', _SESSION_FIXTURES]
    _body.append(f'''

def test_sessions_get_distinct_ids_{_letter}(two_sessions):
    first, second = two_sessions
    assert first.id != second.id


def test_race_ids_are_ordered_{_letter}(race_ids):
    assert race_ids == sorted(race_ids)


def test_closing_one_leaves_the_other_open_{_letter}(two_sessions):
    first, second = two_sessions
    first.close()
    assert not first.open
    assert second.open
''')
    FILES[f"tests/integration/test_session_{_letter}.py"] = "".join(_body)


# ------------------------------------------------------------- PLANT 6 -----

FILES["ledgerlite/outbox.py"] = '''"""Staged writes, applied by a drain loop."""


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
'''

FILES["tests/integration/_waiting.py"] = '''"""Polling helper used by the outbox tests."""

import time

POLL_INTERVAL = 0.05
MAX_POLLS = 40


def wait_until_drained(outbox) -> None:
    """Block until `outbox` reports that it has drained.

    Polls at POLL_INTERVAL and gives up after MAX_POLLS attempts.
    """
    for _ in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        if outbox.is_drained():
            return
    raise TimeoutError("outbox did not drain within the poll budget")
'''

FILES["tests/integration/test_outbox.py"] = '''"""Outbox staging and drain behaviour."""

from ledgerlite.outbox import Outbox

from ._waiting import wait_until_drained


def test_staged_write_is_applied_after_drain():
    outbox = Outbox()
    outbox.stage("entry-1", 10)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("entry-1") == 10


def test_staging_alone_does_not_apply():
    outbox = Outbox()
    outbox.stage("entry-2", 20)
    assert outbox.get("entry-2") is None
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("entry-2") == 20


def test_tick_applies_exactly_one_entry():
    outbox = Outbox()
    outbox.stage("a", 1)
    outbox.stage("b", 2)
    outbox.tick()
    assert outbox.pending_count() == 1
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("b") == 2


def test_last_write_wins_for_repeated_key():
    outbox = Outbox()
    outbox.stage("dup", 1)
    outbox.stage("dup", 9)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("dup") == 9


def test_unknown_key_reads_as_none():
    outbox = Outbox()
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("never-staged") is None


def test_drain_is_idempotent():
    outbox = Outbox()
    outbox.stage("once", 5)
    outbox.drain()
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("once") == 5


def test_empty_outbox_reports_drained():
    outbox = Outbox()
    wait_until_drained(outbox)
    assert outbox.is_drained()


def test_zero_value_is_applied():
    outbox = Outbox()
    outbox.stage("zero", 0)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("zero") == 0


def test_negative_value_is_applied():
    outbox = Outbox()
    outbox.stage("neg", -42)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("neg") == -42


def test_separate_keys_do_not_interfere():
    outbox = Outbox()
    outbox.stage("left", 1)
    outbox.stage("right", 2)
    outbox.drain()
    wait_until_drained(outbox)
    assert (outbox.get("left"), outbox.get("right")) == (1, 2)


def test_large_batch_drains_completely():
    outbox = Outbox()
    for i in range(50):
        outbox.stage(f"bulk-{i}", i)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.pending_count() == 0
    assert outbox.get("bulk-49") == 49


def test_pending_count_tracks_staging():
    outbox = Outbox()
    assert outbox.pending_count() == 0
    outbox.stage("p", 1)
    assert outbox.pending_count() == 1
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.pending_count() == 0


def test_entries_apply_in_staged_order():
    outbox = Outbox()
    outbox.stage("order", 1)
    outbox.stage("order", 2)
    outbox.stage("order", 3)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("order") == 3


def test_fresh_outbox_starts_empty():
    outbox = Outbox()
    wait_until_drained(outbox)
    assert outbox.pending_count() == 0
    assert outbox.get("anything") is None
'''

# ------------------------------------------------------------- PLANT 7 -----

FILES["ledgerlite/registry.py"] = '''"""Per-account rate overrides."""

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
'''

FILES["tests/unit/test_overrides.py"] = '''"""Rate overrides, and assorted accrual arithmetic."""

from decimal import Decimal

import pytest

from ledgerlite.rates import accrue
from ledgerlite.registry import REGISTRY


@pytest.fixture(autouse=True)
def clean_registry():
    REGISTRY.reset()
    yield


def test_accrue_over_zero_days_is_zero():
    assert accrue(1000, 500, 0) == 0


def test_accrue_grows_with_days():
    assert accrue(1000, 500, 10) > accrue(1000, 500, 5)


def test_accrue_grows_with_principal():
    assert accrue(2000, 500, 10) > accrue(1000, 500, 10)


def test_accrue_grows_with_rate():
    assert accrue(1000, 900, 10) > accrue(1000, 500, 10)


def test_accrue_at_zero_rate_is_zero():
    assert accrue(1000, 0, 30) == 0


def test_accrue_on_zero_principal_is_zero():
    assert accrue(0, 500, 30) == 0


def test_accrue_returns_a_decimal():
    assert isinstance(accrue(1000, 500, 1), Decimal)


def test_accrue_is_linear_in_days():
    assert accrue(1000, 500, 20) == accrue(1000, 500, 10) * 2


def test_accrue_rejects_negative_days():
    with pytest.raises(ValueError):
        accrue(1000, 500, -1)


def test_accrue_rejects_negative_rate():
    with pytest.raises(ValueError):
        accrue(1000, -1, 30)


def test_accrue_handles_a_long_horizon():
    assert accrue(1000, 500, 3650) > 0


def test_accrue_of_one_day_is_positive():
    assert accrue(1000, 500, 1) > 0


def test_accrue_is_additive_across_split_periods():
    whole = accrue(1000, 500, 30)
    split = accrue(1000, 500, 10) + accrue(1000, 500, 20)
    assert whole == split


def test_accrue_at_one_basis_point_is_tiny():
    assert accrue(1000, 1, 1) < Decimal("0.001")


def test_override_round_trips():
    assert REGISTRY.get("assets") is None
    REGISTRY.set_override("assets", 500)
    assert REGISTRY.get("assets") == 500
    assert REGISTRY.count() == 1


def test_override_rejects_a_negative_rate():
    with pytest.raises(ValueError):
        REGISTRY.set_override("assets", -1)


def test_override_does_not_leak_between_tests():
    assert REGISTRY.get("assets") is None
    assert REGISTRY.count() == 0
'''


def main() -> None:
    if os.path.exists(ROOT):
        shutil.rmtree(ROOT)
    for relpath, content in FILES.items():
        path = os.path.join(ROOT, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(content)
    print(f"wrote {len(FILES)} files to {ROOT}")


if __name__ == "__main__":
    main()
