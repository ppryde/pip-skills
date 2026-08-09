from scripts.calibration import calibrate
from scripts.models import Card


def done(cid, band, est, act):
    return Card(id=cid, title=f"T {cid}", status="done", complexity=band,
                created="2026-07-01", updated="2026-07-05T10:00",
                budget_estimate=est, budget_actual=act, body="x")


class TestCalibrate:
    def test_band_ratio_and_multiplier(self):
        cards = [
            done("WF-001", "S", 100_000, 140_000),
            done("WF-002", "S", 100_000, 140_000),
        ]
        out = calibrate(cards)
        assert out["bands"]["S"]["count"] == 2
        assert out["bands"]["S"]["median"] == 1.4
        assert out["bands"]["S"]["multiplier"] == 1.4

    def test_within_band_no_multiplier(self):
        out = calibrate([done("WF-003", "M", 100_000, 110_000)])
        assert out["bands"]["M"]["multiplier"] is None

    def test_skips_missing_estimate_and_non_done(self):
        cards = [
            done("WF-004", "L", 0, 500_000),          # no estimate -> skipped
            Card(id="WF-005", title="x", status="in-flight", complexity="L",
                 budget_estimate=700_000, budget_actual=600_000,
                 created="2026-07-01", updated="2026-07-05T10:00", body="x"),
        ]
        out = calibrate(cards)
        assert out["bands"]["L"]["count"] == 0
        assert out["skipped"] == 1  # only the done-but-unusable card counts

    def test_empty_band_shape(self):
        out = calibrate([])
        assert out["bands"]["S"] == {
            "count": 0, "median": None, "mean": None, "multiplier": None
        }
