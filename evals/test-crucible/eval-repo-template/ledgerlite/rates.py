"""Interest rate arithmetic."""

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
