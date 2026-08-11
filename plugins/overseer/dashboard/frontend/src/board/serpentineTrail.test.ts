import { describe, expect, it } from "vitest";
import {
  ARC_PX_PER_UNIT_SERPENTINE,
  SERPENTINE_BAND_HEIGHT_PX,
  SERPENTINE_SWEEP_MAX_FRACTION,
  SERPENTINE_SWEEP_MIN_FRACTION,
  SERPENTINE_TURN_RADIUS_PX,
  serpentineTrail,
} from "./serpentineTrail";

const COLUMN_WIDTH = 320;

function polylineLength(
  pointAt: (arcLength: number) => { x: number; y: number },
  a0: number,
  a1: number
) {
  const steps = 400;
  let length = 0;
  let prev = pointAt(a0);
  for (let i = 1; i <= steps; i++) {
    const a = a0 + (a1 - a0) * (i / steps);
    const cur = pointAt(a);
    length += Math.hypot(cur.x - prev.x, cur.y - prev.y);
    prev = cur;
  }
  return length;
}

describe("ARC_PX_PER_UNIT_SERPENTINE / average vertical advance", () => {
  // HANDOFF (user amendment, 2026-08-11): "vertical advance per complexity
  // point reduced to roughly half the old flat scale (tune ~36-44px/unit)
  // ... the old flat V_PX_PER_UNIT = 72 straight drop is superseded". Once
  // positioning went genuinely arc-length-based (round 2, finding 2), this
  // constant is an ARC-length rate, not a literal vertical one — the
  // vertical-advance target now holds as an AVERAGE, calibrated at
  // AtlasTrailVertical.tsx's own DEFAULT_COLUMN_WIDTH.
  it("the average vertical advance per weight unit lands within HANDOFF's 36-44px/unit tuned range", () => {
    const DEFAULT_COLUMN_WIDTH = 280;
    const { pointAt } = serpentineTrail(DEFAULT_COLUMN_WIDTH, 0.4);
    for (const weight of [1, 2, 4, 7, 14, 28]) {
      const y = pointAt(weight * ARC_PX_PER_UNIT_SERPENTINE).y;
      const avgRate = y / weight;
      expect(avgRate).toBeGreaterThanOrEqual(34); // small slack either side of
      expect(avgRate).toBeLessThanOrEqual(46); // the tuned range for wobble/rounding noise
    }
  });

  it("a 7-child epic (worst case: XL each, 28 weight units) fits comfortably in about one phone screen below its card", () => {
    const DEFAULT_COLUMN_WIDTH = 280;
    const { pointAt } = serpentineTrail(DEFAULT_COLUMN_WIDTH, 0.4);
    const worstCaseHeight = pointAt(28 * ARC_PX_PER_UNIT_SERPENTINE).y;
    expect(worstCaseHeight).toBeLessThan(1500); // well under a typical phone's scrollable screen
  });
});

describe("SERPENTINE_TURN_RADIUS_PX", () => {
  it("is small relative to the band height, so most of each band stays a plain straight cruise leg", () => {
    expect(SERPENTINE_TURN_RADIUS_PX).toBeLessThan(SERPENTINE_BAND_HEIGHT_PX / 4);
  });
});

describe("serpentineTrail", () => {
  it("sweeps x between ~15% and ~85% of the column width (wobble aside)", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    for (let a = 0; a <= 1000; a += 15) {
      const { x } = pointAt(a);
      const min = COLUMN_WIDTH * SERPENTINE_SWEEP_MIN_FRACTION - 20; // wobble tolerance
      const max = COLUMN_WIDTH * SERPENTINE_SWEEP_MAX_FRACTION + 20;
      expect(x).toBeGreaterThanOrEqual(min);
      expect(x).toBeLessThanOrEqual(max);
    }
  });

  it("alternates sweep direction across several bands as arc length grows", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    // Sample a wide arc-length range and confirm x crosses the column's
    // centre repeatedly (a genuine zigzag), not just drifting to one side.
    let crossings = 0;
    let lastSide: "left" | "right" | null = null;
    for (let a = 0; a <= 1200; a += 20) {
      const side = pointAt(a).x < COLUMN_WIDTH / 2 ? "left" : "right";
      if (lastSide && side !== lastSide) crossings++;
      lastSide = side;
    }
    expect(crossings).toBeGreaterThanOrEqual(3);
  });

  it("y is monotonically non-decreasing with arc length, and never exceeds the arc length itself", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.2);
    let prevY = -Infinity;
    for (let a = 0; a <= 1000; a += 10) {
      const { y } = pointAt(a);
      expect(y).toBeGreaterThanOrEqual(prevY);
      expect(y).toBeLessThanOrEqual(a + 0.01); // arc length >= vertical distance, always
      prevY = y;
    }
  });

  it("d() produces an SVG path string starting at arc-length a0 and ending at a1", () => {
    const { d, pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    const path = d(0, 400);
    expect(path.startsWith("M")).toBe(true);
    expect(path).toContain(" L");
    const start = pointAt(0);
    expect(path.startsWith(`M${start.x.toFixed(1)} ${start.y.toFixed(1)}`)).toBe(true);
  });

  // Impl-review round 2, finding 2: "smooth rounded bends (meander/
  // U-turns), not sharp V-points — the hand-wobbled character applies to
  // the turns too." A sharp V has an instantaneous slope reversal at the
  // corner; a rounded bend's slope (dx/d(arcLength)) changes GRADUALLY
  // across a small window around the turn.
  describe("rounded turns (not sharp V-points)", () => {
    function findABandBoundaryArcLength(pointAt: (a: number) => { x: number; y: number }): number {
      // Walk arc length forward until y crosses a SERPENTINE_BAND_HEIGHT_PX
      // multiple — that's where the y-space band boundary (and its turn)
      // sits, wherever it lands in arc-length terms for this seed/width.
      for (let a = 1; a <= 3000; a += 1) {
        const y = pointAt(a).y;
        const bandsPassed = Math.floor(y / SERPENTINE_BAND_HEIGHT_PX);
        const prevY = pointAt(a - 1).y;
        const prevBandsPassed = Math.floor(prevY / SERPENTINE_BAND_HEIGHT_PX);
        if (bandsPassed > prevBandsPassed) return a;
      }
      throw new Error("no band boundary found in range — test fixture assumption broke");
    }

    it("the slope (dx/d(arcLength)) changes gradually through a turn, never in one small step", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.55);
      const boundaryArc = findABandBoundaryArcLength(pointAt);

      // Sample a small window straddling the turn and compute the
      // discrete slope between consecutive samples — a sharp V would show
      // one huge slope-delta right at the corner; a rounded bend spreads
      // the direction change across several samples.
      const step = 1;
      const window = 30;
      const slopes: number[] = [];
      for (let a = boundaryArc - window; a < boundaryArc + window; a += step) {
        const p0 = pointAt(a);
        const p1 = pointAt(a + step);
        slopes.push((p1.x - p0.x) / step);
      }

      const slopeDeltas = slopes.slice(1).map((s, i) => Math.abs(s - slopes[i]));
      const maxSingleStepDelta = Math.max(...slopeDeltas);
      const totalSlopeChange = Math.abs(slopes[slopes.length - 1] - slopes[0]);

      // A rounded turn spreads the reversal out — no ONE consecutive-sample
      // step should account for anywhere near the WHOLE direction change.
      expect(maxSingleStepDelta).toBeLessThan(totalSlopeChange * 0.5);
    });
  });

  // Arc-length proportionality — now genuinely exact (round 2, finding 2's
  // arc-length parameterization), including across a turn, which the
  // pre-rounding constant-slope shortcut could never have honestly
  // asserted (a rounded corner locally shortens the path — see
  // serpentineTrail.ts's module doc comment — so only TRUE arc-length
  // parameterization, not a raw-y shortcut, can make this hold at a turn).
  describe("arc-length proportionality (same weight = same length) — exact, by construction", () => {
    it("polyline length between two arc-length values equals their difference, to within sampling error", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.7);
      for (const [a0, a1] of [
        [10, 50],
        [130, 170], // no boundary in range
        [300, 340],
        [160, 300], // SPANS at least one band boundary/turn
        [0, 500],
      ]) {
        const measured = polylineLength(pointAt, a0, a1);
        const expected = a1 - a0;
        expect(measured).toBeCloseTo(expected, 0); // within ~0.5px sampling error
      }
    });

    it("two equal-arc-delta ranges have equal length regardless of which band(s)/turns they fall in", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.7);
      const lenA = polylineLength(pointAt, 10, 50);
      const lenB = polylineLength(pointAt, 160, 200); // spans a turn
      const lenC = polylineLength(pointAt, 800, 840);
      expect(lenB).toBeCloseTo(lenA, 0);
      expect(lenC).toBeCloseTo(lenA, 0);
    });

    it("arc length scales linearly with the arc-length delta itself", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.3);
      const lenShort = polylineLength(pointAt, 0, 200);
      const lenLong = polylineLength(pointAt, 0, 400);
      expect(lenLong / lenShort).toBeCloseTo(2, 1);
    });
  });
});
