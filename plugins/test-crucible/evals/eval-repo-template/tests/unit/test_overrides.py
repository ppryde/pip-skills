"""Rate overrides, and assorted accrual arithmetic."""

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
