/**
 * Down-mode's serpentine trail geometry (WF-086 v2, HANDOFF's Down-mode
 * user amendment, 2026-08-11, re-amended for a true meander — supersedes
 * the original flat vertical drop). The path sweeps left<->right across
 * ~15%-85% of the column width, in a continuous SINE curve — the classic
 * quest-map meander/river-bend, with NO sharp angle anywhere along the
 * path (impl-review round 2, finding 2 — direct user feedback: "love the
 * extra bends but they should meander not turn sharply").
 *
 * A sine is infinitely smooth (C-infinity, not merely tangent-continuous)
 * everywhere by construction — there is no piecewise "band" geometry to
 * blend/round at all, so there is structurally no boundary where a kink
 * could ever reappear. This SUPERSEDES an earlier version of this module
 * that modeled the sweep as piecewise-LINEAR legs with a small rounded
 * blend only near each direction change — that read as "mostly straight
 * with rounded corners" rather than a genuine continuous meander once
 * rendered at phone size.
 *
 * Arc length is still not proportional to `y` in closed form here (`dx/dy`
 * varies continuously along a sine, unlike a constant-slope straight leg),
 * so this module parameterizes markers by TRUE ARC LENGTH directly, not by
 * `y`: `pointAt`'s input is a cumulative arc-length scalar (built once per
 * trail via a sampled lookup table, inverted by binary search), which is
 * what makes "same weight = same length" (HANDOFF: "weight is measured
 * along the path") hold in path-arc terms EXACTLY regardless of the curve
 * shape — see `buildArcLengthTable` below. `atlasTrailLayout.ts`'s
 * existing `computeSegments`/`boundaryX`/`campfireX`/etc. are reused
 * completely unchanged for Down mode — they already operate on a generic
 * "distance along the trail" scalar, which is arc length here (their
 * `pxPerWeight` argument is fed `ARC_PX_PER_UNIT_SERPENTINE`, an
 * ARC-length rate, not a vertical one).
 */

const WOBBLE_AMPLITUDE = 12;
const WOBBLE_K = (2 * Math.PI) / 300;

/** How far into the column's own width the sweep travels — HANDOFF:
 * "~15%-85%", "the path sweeps left<->right across MOST of the column
 * width". The sine's own amplitude/centre are derived from these. */
export const SERPENTINE_SWEEP_MIN_FRACTION = 0.15;
export const SERPENTINE_SWEEP_MAX_FRACTION = 0.85;

/** Half the sine's period — the vertical distance between the path's
 * centreline crossing and the next wall it visits (a full left-wall ->
 * centre -> right-wall -> centre cycle spans two of these). Purely a
 * cosmetic tuning knob: since positioning is arc-length-parameterized
 * (module doc comment), changing this can never break "same weight = same
 * length" — it only changes how many meanders a given trail visually has. */
export const SERPENTINE_BAND_HEIGHT_PX = 90;

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
export const ARC_PX_PER_UNIT_SERPENTINE = 105;

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
  const centreX = (xLeft + xRight) / 2;
  const amplitude = (xRight - xLeft) / 2;

  /** The meander itself: a plain sine in y, oscillating between xLeft and
   * xRight with a soft, continuous curve throughout — never a straight
   * leg, never a corner. `WOBBLE_AMPLITUDE`'s small high-frequency ripple
   * rides on top, unchanged from Across mode's own `wobblePath` character. */
  function rawPointAtY(y: number): { x: number; y: number } {
    const baseX = centreX + amplitude * Math.sin((Math.PI * y) / SERPENTINE_BAND_HEIGHT_PX);
    const wobble = WOBBLE_AMPLITUDE * Math.sin(WOBBLE_K * y + seed);
    return { x: baseX + wobble, y };
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
