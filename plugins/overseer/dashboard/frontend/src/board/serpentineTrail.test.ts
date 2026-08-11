import { describe, expect, it } from "vitest";
import {
  ARC_PX_PER_UNIT_SERPENTINE,
  SERPENTINE_SWEEP_MAX_FRACTION,
  SERPENTINE_SWEEP_MIN_FRACTION,
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
    for (const weight of [2, 4, 7, 14, 28]) {
      const y = pointAt(weight * ARC_PX_PER_UNIT_SERPENTINE).y;
      const avgRate = y / weight;
      expect(avgRate).toBeGreaterThanOrEqual(34); // small slack either side of
      expect(avgRate).toBeLessThanOrEqual(46); // the tuned range for wobble/curvature noise
    }
  });

  it("a 7-child epic (worst case: XL each, 28 weight units) fits comfortably in about one phone screen below its card", () => {
    const DEFAULT_COLUMN_WIDTH = 280;
    const { pointAt } = serpentineTrail(DEFAULT_COLUMN_WIDTH, 0.4);
    const worstCaseHeight = pointAt(28 * ARC_PX_PER_UNIT_SERPENTINE).y;
    expect(worstCaseHeight).toBeLessThan(1500); // well under a typical phone's scrollable screen
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

  it("alternates sweep direction across several meanders as arc length grows", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    // Sample a wide arc-length range and confirm x crosses the column's
    // centre repeatedly (a genuine meander), not just drifting to one side.
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

  // Impl-review round 2, finding 2 (direct user feedback: "love the extra
  // bends but they should meander not turn sharply to keep the rounded
  // friendly feel" — "NO sharp angle anywhere along the path"). A pure
  // sine curve is C-infinity smooth everywhere by construction, but this
  // asserts it empirically rather than trusting the math alone: the
  // discrete slope (dx/d(arcLength)) never jumps sharply between
  // consecutive samples, ANYWHERE along a long stretch of the path — not
  // just near wherever an old piecewise-band boundary used to sit.
  describe("no sharp angle anywhere along the path (true meander)", () => {
    it("the discrete slope changes smoothly at every point sampled — no single-step jump anywhere close to the full slope range", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.55);
      const step = 1;
      const slopes: number[] = [];
      for (let a = 0; a <= 1000; a += step) {
        const p0 = pointAt(a);
        const p1 = pointAt(a + step);
        slopes.push((p1.x - p0.x) / step);
      }
      const slopeDeltas = slopes.slice(1).map((s, i) => Math.abs(s - slopes[i]));
      const maxSingleStepDelta = Math.max(...slopeDeltas);
      const slopeRange = Math.max(...slopes) - Math.min(...slopes);

      // A sharp V-point would show ONE consecutive-sample slope delta
      // comparable to the whole path's slope range (an instant reversal);
      // a true meander's slope changes gradually and continuously, so no
      // single step ever accounts for more than a small fraction of it.
      expect(maxSingleStepDelta).toBeLessThan(slopeRange * 0.15);
    });

    it("is tangent-continuous specifically at the old band-boundary y-values (34*n multiples), not just elsewhere", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.55);
      // Sample straddling several of the OLD piecewise model's boundary
      // y-values directly — the highest-risk points for a regression back
      // toward a corner, now just ordinary points on a smooth sine.
      for (const boundaryY of [90, 180, 270, 360]) {
        const before = pointAt(boundaryY - 1);
        const at = pointAt(boundaryY);
        const after = pointAt(boundaryY + 1);
        const slopeBefore = at.x - before.x;
        const slopeAfter = after.x - at.x;
        expect(Math.abs(slopeAfter - slopeBefore)).toBeLessThan(1); // px, a generous smoothness bound
      }
    });
  });

  // Arc-length proportionality — exact by construction (true arc-length
  // parameterization, see the module doc comment), regardless of the
  // curve's shape.
  describe("arc-length proportionality (same weight = same length) — exact, by construction", () => {
    it("polyline length between two arc-length values equals their difference, to within sampling error", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.7);
      for (const [a0, a1] of [
        [10, 50],
        [130, 170],
        [300, 340],
        [160, 300],
        [0, 500],
      ]) {
        const measured = polylineLength(pointAt, a0, a1);
        const expected = a1 - a0;
        expect(measured).toBeCloseTo(expected, 0); // within ~0.5px sampling error
      }
    });

    it("two equal-arc-delta ranges have equal length regardless of where along the meander they fall", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.7);
      const lenA = polylineLength(pointAt, 10, 50);
      const lenB = polylineLength(pointAt, 160, 200);
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
