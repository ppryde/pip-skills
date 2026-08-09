"""Rate conversion tests."""

from decimal import Decimal

import pytest

from ledgerlite.rates import BASIS, accrue, annual_to_daily

def test_annual_to_daily_zero_rate():
    result = annual_to_daily(0)
    assert result == (Decimal(0) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_one_bp():
    result = annual_to_daily(1)
    assert result == (Decimal(1) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_fifty_bps():
    result = annual_to_daily(50)
    assert result == (Decimal(50) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_one_hundred_bps():
    result = annual_to_daily(100)
    assert result == (Decimal(100) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_five_hundred_bps():
    result = annual_to_daily(500)
    assert result == (Decimal(500) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_one_thousand_bps():
    result = annual_to_daily(1000)
    assert result == (Decimal(1000) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_two_thousand_bps():
    result = annual_to_daily(2000)
    assert result == (Decimal(2000) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_five_thousand_bps():
    result = annual_to_daily(5000)
    assert result == (Decimal(5000) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_ten_thousand_bps():
    result = annual_to_daily(10000)
    assert result == (Decimal(10000) / BASIS) / Decimal(365)
    assert result >= 0

def test_annual_to_daily_max_bps():
    result = annual_to_daily(99999)
    assert result == (Decimal(99999) / BASIS) / Decimal(365)
    assert result >= 0

def test_negative_rate_rejected():
    with pytest.raises(ValueError):
        annual_to_daily(-1)


def test_negative_days_rejected():
    with pytest.raises(ValueError):
        accrue(1000, 500, -1)
