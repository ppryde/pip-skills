"""Pure estimation calibration over completed cards. No writes."""
from __future__ import annotations

from statistics import mean, median

from scripts.models import Card

BANDS = ("S", "M", "L")
_DRIFT = 0.25


def calibrate(cards: list[Card]) -> dict:
    done = [c for c in cards if c.status == "done"]
    by_band: dict[str, list[float]] = {b: [] for b in BANDS}
    skipped = 0
    for c in done:
        if c.complexity in BANDS and c.budget_estimate and c.budget_actual:
            by_band[c.complexity].append(c.budget_actual / c.budget_estimate)
        else:
            skipped += 1
    bands: dict[str, dict] = {}
    for b in BANDS:
        ratios = by_band[b]
        if not ratios:
            bands[b] = {"count": 0, "median": None, "mean": None,
                        "multiplier": None}
            continue
        med = median(ratios)
        bands[b] = {
            "count": len(ratios),
            "median": round(med, 3),
            "mean": round(mean(ratios), 3),
            "multiplier": round(med, 2) if abs(med - 1.0) > _DRIFT else None,
        }
    return {"bands": bands, "skipped": skipped}
