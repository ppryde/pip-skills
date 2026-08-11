/**
 * Down-mode's serpentine trail geometry (WF-086 v2, HANDOFF's Down-mode
 * user amendment, 2026-08-11 — supersedes the original flat vertical
 * drop). The path sweeps left<->right across ~15%-85% of the column
 * width, alternating direction every fixed-height "band", so path length
 * is spent horizontally and the column stays short.
 *
 * Key trick that makes this simple: within any one band, `x` is a LINEAR
 * function of `y` (a straight diagonal leg, wobble aside) with the SAME
 * slope magnitude in every band (only the sign flips). That makes the
 * arc-length differential `ds/dy = sqrt(1 + (dx/dy)^2)` a single CONSTANT
 * across the whole trail — so arc length is exactly proportional to `y`,
 * which `atlasTrailLayout.ts`'s existing `computeSegments`/`boundaryX`/
 * `campfireX`/etc. already make exactly proportional to cumulative WEIGHT
 * (they're reused as-is for Down mode, just fed `V_PX_PER_UNIT_SERPENTINE`
 * as their "pxPerWeight" and treating their scalar output as a Y
 * coordinate instead of an X one). "Same weight = same length" in
 * path-arc terms falls out of the geometry, with no separate arc-length
 * inversion/parameterization step needed.
 */

const WOBBLE_AMPLITUDE = 12;
const WOBBLE_K = (2 * Math.PI) / 300;

/** How far into the column's own width the sweep travels — HANDOFF:
 * "~15%-85%", "the path sweeps left<->right across MOST of the column
 * width". */
export const SERPENTINE_SWEEP_MIN_FRACTION = 0.15;
export const SERPENTINE_SWEEP_MAX_FRACTION = 0.85;

/** Visual sweep cadence — how tall (in y) one full left-right (or
 * right-left) leg is. Purely a cosmetic tuning knob: it does not affect
 * "same weight = same length" (see the module doc comment), only how many
 * zigzags a given trail visually has. */
export const SERPENTINE_BAND_HEIGHT_PX = 90;

/** Vertical advance per complexity point (HANDOFF, user amendment): "roughly
 * half the old flat scale ... tune ~36-44px/unit so a 7-child epic fits in
 * ≈1 phone screen below its card" — supersedes the original flat
 * `V_PX_PER_UNIT = 72` straight drop. */
export const V_PX_PER_UNIT_SERPENTINE = 40;

export interface SerpentineTrail {
  /** The serpentine's (wobbled) point at a given Y — Y only ever grows
   * downward; the serpentine displaces X, never Y itself. */
  pointAt: (y: number) => { x: number; y: number };
  /** A sampled SVG path `d` string marching from y0 to y1 (y0 may be
   * greater than y1 — the caller decides direction, mirroring
   * `wobblePath`'s own `x0`/`x1` contract). */
  d: (y0: number, y1: number) => string;
}

/**
 * Builds one epic's serpentine trail for a column of the given width.
 * `seed` phase-shifts the wobble exactly like `wobblePath`/`wobblePathVertical`
 * (`seedFor(card.id)`) — same hand-drawn-line character, same
 * never-in-lockstep-with-a-neighbour rationale.
 */
export function serpentineTrail(columnWidth: number, seed: number): SerpentineTrail {
  const xLeft = columnWidth * SERPENTINE_SWEEP_MIN_FRACTION;
  const xRight = columnWidth * SERPENTINE_SWEEP_MAX_FRACTION;
  const sweepWidth = xRight - xLeft;

  function pointAt(y: number): { x: number; y: number } {
    const yClamped = Math.max(y, 0);
    const bandIndex = Math.floor(yClamped / SERPENTINE_BAND_HEIGHT_PX);
    const localT = (yClamped - bandIndex * SERPENTINE_BAND_HEIGHT_PX) / SERPENTINE_BAND_HEIGHT_PX;
    const leftToRight = bandIndex % 2 === 0;
    const baseX = leftToRight ? xLeft + sweepWidth * localT : xRight - sweepWidth * localT;
    const wobble = WOBBLE_AMPLITUDE * Math.sin(WOBBLE_K * y + seed);
    return { x: baseX + wobble, y };
  }

  function d(y0: number, y1: number): string {
    const steps = Math.max(2, Math.round(Math.abs(y1 - y0) / 10));
    let path = "";
    for (let i = 0; i <= steps; i++) {
      const y = y0 + (y1 - y0) * (i / steps);
      const { x } = pointAt(y);
      path += (i ? " L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }
    return path;
  }

  return { pointAt, d };
}
