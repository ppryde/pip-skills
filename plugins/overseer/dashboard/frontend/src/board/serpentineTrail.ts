/**
 * Down-mode's serpentine trail geometry (WF-086 v2, HANDOFF's Down-mode
 * user amendment, 2026-08-11, re-amended for rounded turns — supersedes
 * the original flat vertical drop). The path sweeps left<->right across
 * ~15%-85% of the column width, alternating direction every fixed-height
 * "band", with the direction changes SMOOTHED into rounded bends
 * (meander/U-turns, not sharp V-points — impl-review round 2, finding 2)
 * — so path length is spent horizontally and the column stays short.
 *
 * Rounding a corner necessarily shortens the path locally versus going all
 * the way into the sharp point and back out (that's just geometry — any
 * smoothing of a kink removes some length). That breaks the earlier
 * "constant slope-per-band, so arc length is trivially proportional to y"
 * shortcut this module used before the turns were rounded: `ds/dy` is no
 * longer constant near a turn. So this module now parameterizes markers by
 * TRUE ARC LENGTH directly, not by `y`: `pointAt`'s input is a cumulative
 * arc-length scalar (built once per trail via a sampled lookup table,
 * inverted by binary search), which is what actually makes "same weight =
 * same length" hold in path-arc terms EXACTLY, regardless of how much of
 * that length a turn's rounding ate into — see `buildArcLengthTable`
 * below. `atlasTrailLayout.ts`'s existing `computeSegments`/`boundaryX`/
 * `campfireX`/etc. are still reused completely unchanged for Down mode —
 * they already operate on a generic "distance along the trail" scalar,
 * which is arc length here (their `pxPerWeight` argument is fed
 * `ARC_PX_PER_UNIT_SERPENTINE`, an ARC-length rate, not a vertical one).
 */

const WOBBLE_AMPLITUDE = 12;
const WOBBLE_K = (2 * Math.PI) / 300;

/** How far into the column's own width the sweep travels — HANDOFF:
 * "~15%-85%", "the path sweeps left<->right across MOST of the column
 * width". */
export const SERPENTINE_SWEEP_MIN_FRACTION = 0.15;
export const SERPENTINE_SWEEP_MAX_FRACTION = 0.85;

/** Visual sweep cadence — how tall (in y) one full left-right (or
 * right-left) leg is, corner-rounding aside. Purely a cosmetic tuning
 * knob: since positioning is arc-length-parameterized (module doc
 * comment), changing this can never break "same weight = same length" —
 * it only changes how many zigzags a given trail visually has. */
export const SERPENTINE_BAND_HEIGHT_PX = 90;

/** Half-width (in y) of the smoothing zone around each band boundary
 * (impl-review round 2, finding 2: "smooth rounded bends... not sharp
 * V-points") — small relative to `SERPENTINE_BAND_HEIGHT_PX` so most of
 * each band stays a plain straight "cruise" leg, only the corner itself
 * rounds off. */
export const SERPENTINE_TURN_RADIUS_PX = 10;

/** Arc-length px per complexity point (HANDOFF's "weight is measured
 * along the path"; impl-review round 2 renamed this from
 * `V_PX_PER_UNIT_SERPENTINE` once positioning became genuinely
 * arc-length-based — the old name implied a literal VERTICAL rate, which
 * this constant no longer directly is). Calibrated against
 * `SERPENTINE_BAND_HEIGHT_PX`/`SERPENTINE_SWEEP_*` at a representative
 * ~280px column width (`AtlasTrailVertical.tsx`'s own
 * `DEFAULT_COLUMN_WIDTH`) so the resulting AVERAGE vertical advance lands
 * in HANDOFF's tuned ~36-44px/complexity-point range (roughly half the
 * superseded flat `V_PX_PER_UNIT = 72` straight drop) — see
 * `serpentineTrail.test.ts`'s "average vertical advance" coverage. A
 * real column's own width can pull this mildly off that average (a wider
 * column's sweep travels more horizontally per unit of arc length, so
 * makes mildly LESS vertical progress per weight unit, and vice versa) —
 * expected and consistent with "same weight = same length" being an
 * ARC-length invariant, not a per-column vertical-height one.
 */
export const ARC_PX_PER_UNIT_SERPENTINE = 96;

/** How far (in y) the sampled arc-length lookup table extends — generous
 * enough for any realistic epic (a 7-child, all-XL epic needs well under
 * half of this); `yAtArcLength` clamps to the table's own end for a
 * pathologically heavy epic that somehow exceeds it, rather than
 * crashing. */
const MAX_TABLE_Y_PX = 6000;
const TABLE_SAMPLE_STEP_PX = 3;

export interface SerpentineTrail {
  /** The serpentine's (wobbled) point at a given cumulative ARC LENGTH
   * (not a raw y — see the module doc comment for why). */
  pointAt: (arcLength: number) => { x: number; y: number };
  /** A sampled SVG path `d` string marching from arc-length a0 to a1 (a0
   * may be greater than a1 — the caller decides direction, mirroring
   * `wobblePath`'s own `x0`/`x1` contract). */
  d: (a0: number, a1: number) => string;
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

  /** The un-rounded, piecewise-LINEAR sweep — a straight diagonal leg per
   * band, sign-flipping each band. Sharp kinks at every boundary; only
   * ever called by `roundedBaseX` below (as the raw material for its
   * corner blend) and never exposed directly. */
  function rawBaseX(y: number): number {
    const yClamped = Math.max(y, 0);
    const bandIndex = Math.floor(yClamped / SERPENTINE_BAND_HEIGHT_PX);
    const localT = (yClamped - bandIndex * SERPENTINE_BAND_HEIGHT_PX) / SERPENTINE_BAND_HEIGHT_PX;
    const leftToRight = bandIndex % 2 === 0;
    return leftToRight ? xLeft + sweepWidth * localT : xRight - sweepWidth * localT;
  }

  /** Rounds the corner at each band boundary: within
   * `SERPENTINE_TURN_RADIUS_PX` of a boundary, blends the two adjacent
   * straight legs via a trapezoidal (area-preserving) average instead of
   * meeting at the raw sharp point — a smooth meander, not a V. Outside
   * that small zone (most of each band), returns `rawBaseX` UNCHANGED —
   * the "cruise" portion of every band stays a plain straight leg. */
  function roundedBaseX(y: number): number {
    const yClamped = Math.max(y, 0);
    const nearestBoundary = Math.round(yClamped / SERPENTINE_BAND_HEIGHT_PX) * SERPENTINE_BAND_HEIGHT_PX;
    const dist = Math.abs(yClamped - nearestBoundary);
    // No corner to round at the very start of the trail (nothing before
    // y=0 to blend into) or once far enough from the nearest boundary.
    if (nearestBoundary <= 0 || dist >= SERPENTINE_TURN_RADIUS_PX) return rawBaseX(y);

    const a = yClamped - SERPENTINE_TURN_RADIUS_PX;
    const b = yClamped + SERPENTINE_TURN_RADIUS_PX;
    const beforeLen = nearestBoundary - a;
    const afterLen = b - nearestBoundary;
    const xa = rawBaseX(a);
    const xBoundary = rawBaseX(nearestBoundary);
    const xb = rawBaseX(b);
    // Trapezoidal average of the two adjacent straight legs over [a, b],
    // evaluated at y — exact for a piecewise-linear function.
    const integral = ((xa + xBoundary) / 2) * beforeLen + ((xBoundary + xb) / 2) * afterLen;
    return integral / (2 * SERPENTINE_TURN_RADIUS_PX);
  }

  function rawPointAtY(y: number): { x: number; y: number } {
    const wobble = WOBBLE_AMPLITUDE * Math.sin(WOBBLE_K * y + seed);
    return { x: roundedBaseX(y) + wobble, y };
  }

  /** Sampled {y, cumulative arc length} table, built once per trail
   * (memoized in this closure — `serpentineTrail` is called once per
   * component render, not per marker). `yAtArcLength` inverts it via
   * binary search + linear interpolation between the bracketing samples. */
  function buildArcLengthTable(): { y: number; arcLen: number }[] {
    const table: { y: number; arcLen: number }[] = [{ y: 0, arcLen: 0 }];
    let prev = rawPointAtY(0);
    let acc = 0;
    for (let y = TABLE_SAMPLE_STEP_PX; y <= MAX_TABLE_Y_PX; y += TABLE_SAMPLE_STEP_PX) {
      const cur = rawPointAtY(y);
      acc += Math.hypot(cur.x - prev.x, cur.y - prev.y);
      table.push({ y, arcLen: acc });
      prev = cur;
    }
    return table;
  }

  const arcLengthTable = buildArcLengthTable();

  function yAtArcLength(targetArcLength: number): number {
    if (targetArcLength <= 0) return 0;
    const last = arcLengthTable[arcLengthTable.length - 1];
    if (targetArcLength >= last.arcLen) return last.y;

    let lo = 0;
    let hi = arcLengthTable.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (arcLengthTable[mid].arcLen < targetArcLength) lo = mid;
      else hi = mid;
    }
    const t0 = arcLengthTable[lo];
    const t1 = arcLengthTable[hi];
    const span = t1.arcLen - t0.arcLen;
    const frac = span > 0 ? (targetArcLength - t0.arcLen) / span : 0;
    return t0.y + (t1.y - t0.y) * frac;
  }

  function pointAt(arcLength: number): { x: number; y: number } {
    return rawPointAtY(yAtArcLength(arcLength));
  }

  function d(a0: number, a1: number): string {
    const steps = Math.max(2, Math.round(Math.abs(a1 - a0) / 10));
    let path = "";
    for (let i = 0; i <= steps; i++) {
      const a = a0 + (a1 - a0) * (i / steps);
      const { x, y } = pointAt(a);
      path += (i ? " L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }
    return path;
  }

  return { pointAt, d };
}
