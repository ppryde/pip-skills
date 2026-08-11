import { describe, expect, it } from "vitest";
import {
  SERPENTINE_SWEEP_MAX_FRACTION,
  SERPENTINE_SWEEP_MIN_FRACTION,
  V_PX_PER_UNIT_SERPENTINE,
  serpentineTrail,
} from "./serpentineTrail";

const COLUMN_WIDTH = 320;

describe("V_PX_PER_UNIT_SERPENTINE", () => {
  // HANDOFF (user amendment, 2026-08-11): "vertical advance per complexity
  // point reduced to roughly half the old flat scale (tune ~36-44px/unit)
  // ... the old flat V_PX_PER_UNIT = 72 straight drop is superseded".
  it("is within HANDOFF's 36-44px/unit tuned range, roughly half the superseded flat 72", () => {
    expect(V_PX_PER_UNIT_SERPENTINE).toBeGreaterThanOrEqual(36);
    expect(V_PX_PER_UNIT_SERPENTINE).toBeLessThanOrEqual(44);
  });

  it("a 7-child epic (weight ~14 at worst, XL each) fits comfortably in about one phone screen below its card", () => {
    // A generous upper bound: 7 XL (weight 4) children => 28 weight units.
    const worstCaseHeight = 28 * V_PX_PER_UNIT_SERPENTINE;
    expect(worstCaseHeight).toBeLessThan(1200); // well under a typical phone's scrollable screen
  });
});

describe("serpentineTrail", () => {
  it("sweeps x between ~15% and ~85% of the column width (wobble aside)", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    for (let y = 0; y <= 400; y += 5) {
      const { x } = pointAt(y);
      const min = COLUMN_WIDTH * SERPENTINE_SWEEP_MIN_FRACTION - 20; // wobble tolerance
      const max = COLUMN_WIDTH * SERPENTINE_SWEEP_MAX_FRACTION + 20;
      expect(x).toBeGreaterThanOrEqual(min);
      expect(x).toBeLessThanOrEqual(max);
    }
  });

  it("alternates sweep direction between successive bands", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    // Sample near the end of band 0 and the end of band 1 — opposite
    // directions land near opposite edges.
    const nearEndOfBand0 = pointAt(89); // just before the band boundary
    const nearEndOfBand1 = pointAt(179);
    // Band 0 sweeps left->right (ends near xRight); band 1 sweeps
    // right->left (ends near xLeft) — their x's land on opposite sides.
    expect(nearEndOfBand0.x).toBeGreaterThan(COLUMN_WIDTH / 2);
    expect(nearEndOfBand1.x).toBeLessThan(COLUMN_WIDTH / 2);
  });

  it("is continuous across a band boundary — no jump in x", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    const justBefore = pointAt(89.99);
    const justAfter = pointAt(90.01);
    expect(Math.abs(justAfter.x - justBefore.x)).toBeLessThan(2);
  });

  it("y always equals the input y (the serpentine only ever displaces x)", () => {
    const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    expect(pointAt(123.4).y).toBe(123.4);
  });

  it("d() produces an SVG path string starting at y0 and ending at y1", () => {
    const { d, pointAt } = serpentineTrail(COLUMN_WIDTH, 0);
    const path = d(0, 200);
    expect(path.startsWith("M")).toBe(true);
    expect(path).toContain(" L");
    const startX = pointAt(0).x;
    expect(path.startsWith(`M${startX.toFixed(1)} 0.0`)).toBe(true);
  });

  // Impl-review round 1, finding 5's explicit test ask: arc-length
  // proportionality — "same weight = same length" must hold in path-ARC
  // terms, not just in raw vertical y terms.
  describe("arc-length proportionality (same weight = same length)", () => {
    function polylineLength(pointAt: (y: number) => { x: number; y: number }, y0: number, y1: number) {
      const steps = 200;
      let length = 0;
      let prev = pointAt(y0);
      for (let i = 1; i <= steps; i++) {
        const y = y0 + (y1 - y0) * (i / steps);
        const cur = pointAt(y);
        length += Math.hypot(cur.x - prev.x, cur.y - prev.y);
        prev = cur;
      }
      return length;
    }

    it("two equal-y-delta ranges have approximately equal arc length, regardless of which band(s) they fall in", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.7);
      // Same 40px y-delta, sampled at different points along several bands.
      // A few px of wobble-induced noise between windows is expected and
      // fine — this asserts the underlying BAND geometry (the dominant
      // term) is uniform, within a generous tolerance for that noise.
      const lenA = polylineLength(pointAt, 10, 50);
      const lenB = polylineLength(pointAt, 130, 170); // spans a band boundary
      const lenC = polylineLength(pointAt, 300, 340);
      const tolerance = 0.1; // 10% relative tolerance
      expect(Math.abs(lenB - lenA) / lenA).toBeLessThan(tolerance);
      expect(Math.abs(lenC - lenA) / lenA).toBeLessThan(tolerance);
    });

    it("arc length scales linearly with y-delta (constant slope-per-band makes arc length proportional to y, hence to weight)", () => {
      const { pointAt } = serpentineTrail(COLUMN_WIDTH, 0.3);
      const lenShort = polylineLength(pointAt, 0, 90);
      const lenLong = polylineLength(pointAt, 0, 180);
      expect(lenLong / lenShort).toBeCloseTo(2, 1);
    });
  });
});
