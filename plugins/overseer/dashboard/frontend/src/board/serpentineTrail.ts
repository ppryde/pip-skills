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
 *
 * Round 3 (HANDOFF, "loops after a certain length"): `rawPointAtY` is now a
 * WEIGHTED SUM of two sine components at different periods/phases (rather
 * than one plain sine), so each epic's own seed produces a genuinely
 * irregular meander instead of one clean repeating wave — and past
 * `LOOP_START_Y` a `smoothstep` cross-fades both the amplitude (toward a
 * much wider sweep) and the dominant component's period (toward a tighter
 * one), so a sufficiently long trail visually tightens into loopy hairpin
 * bends. A sum of sines (with smoothly-varying, not abruptly-switched,
 * coefficients) is exactly as C-infinity smooth as the single sine it
 * extends — see `rawPointAtY`'s own doc comment for why the period itself
 * is cross-faded between two FIXED values rather than swept continuously
 * (which would "chirp" and transiently spike local curvature). The
 * arc-length/"same weight = same length" machinery above is completely
 * unaffected by any of this — it only ever depends on `rawPointAtY` being
 * SOME smooth function of `y`, never on its particular shape.
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

/** "Loops after a certain length" (HANDOFF's Down-mode user amendment,
 * 2026-08-11, re-amended for a genuine loopy meander): below this `y`, the
 * path sweeps its base `SERPENTINE_SWEEP_MIN/MAX_FRACTION` band; from here
 * it ramps toward a much wider band with a shorter dominant period, so a
 * long trail reads as tightening hairpin bends rather than a gentle,
 * regular river-bend throughout. */
export const LOOP_START_Y = 320;
/** How far past `LOOP_START_Y` the ramp takes to fully complete — a
 * `smoothstep` over this span (not a step function), so there is no kink
 * at the threshold itself, only a gradually widening/tightening curve. */
const LOOP_RAMP_PX = 260;
/** The wider sweep band the loop stage ramps toward — HANDOFF: "widen the
 * allowed band, e.g. toward ~5%..95% of column width". */
const LOOP_SWEEP_MIN_FRACTION = 0.05;
const LOOP_SWEEP_MAX_FRACTION = 0.95;
/** Final hard safety clamp on the returned `x` — independent of the sweep
 * bands above (which the small high-frequency wobble can still nudge past
 * slightly) — so the path can NEVER leave the column regardless of seed.
 * Exported (like the sweep fractions above) so tests assert against the
 * same source of truth rather than a duplicated magic number. */
export const SERPENTINE_CLAMP_MIN_FRACTION = 0.04;
export const SERPENTINE_CLAMP_MAX_FRACTION = 0.96;

/** Classic smoothstep (3t²-2t³, clamped to [0,1]) — used to ramp the loop
 * stage in with a continuous derivative (zero slope at both ends), so
 * neither the amplitude nor the dominant period has a kink where the ramp
 * starts or finishes biting. */
function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

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
  const baseAmplitude = (xRight - xLeft) / 2;
  // Both bands share the same centre (their fraction pairs are symmetric
  // around 0.5) — only the amplitude widens at the loop stage, so ramping
  // between the two is a single lerp on amplitude, not on centre too.
  const loopAmplitude =
    (columnWidth * (LOOP_SWEEP_MAX_FRACTION - LOOP_SWEEP_MIN_FRACTION)) / 2;
  const clampMin = columnWidth * SERPENTINE_CLAMP_MIN_FRACTION;
  const clampMax = columnWidth * SERPENTINE_CLAMP_MAX_FRACTION;
  // The loop stage's dominant period — half the base band height, for
  // tighter hairpin bends. A FIXED period (not one that itself varies
  // continuously with `y`) deliberately avoids feeding a time-varying
  // frequency into the sine's own argument (a "chirp"), which would
  // otherwise transiently spike the path's local curvature right where the
  // ramp is climbing — cross-fading the AMPLITUDE between two fixed-period
  // sines (below) blends the two characters smoothly with no such spike.
  const loopPeriod = SERPENTINE_BAND_HEIGHT_PX * 0.5;

  // Seed-derived (deterministic — `Math.random`/`Date.now` are banned, see
  // module invariants) phase and period multiplier for the SECOND sine
  // component below — every epic's own seed picks a different, but always
  // reproducible, longer-period wander, which is what keeps the meander
  // from reading as one clean regular sine repeated forever.
  const secondaryPhase = seed * 2.3 + 1.7;
  const secondaryPeriodMul = 2.2 + ((Math.sin(seed * 4.1) + 1) / 2) * 1.6; // ~2.2x-3.8x the base period

  /** The meander itself: TWO sine components at different periods/phases
   * (HANDOFF, re-amended: "sum 2-3 sine components ... so each epic's path
   * is irregular rather than a clean regular sine") — a dominant one, and a
   * longer, seed-derived secondary wander riding under it, weighted
   * 0.72/0.28 so their sum never exceeds the current `amplitude` (|sin| <=
   * 1 each, weights sum to 1). `WOBBLE_AMPLITUDE`'s small high-frequency
   * ripple still rides on top, unchanged from Across mode's own
   * `wobblePath` character. Past `LOOP_START_Y`, a smoothstep ramps the
   * amplitude toward `loopAmplitude` (a much wider sweep) AND cross-fades
   * the dominant component from the base (gentle) period to `loopPeriod`
   * (tight hairpins) — always smoothly, never a stepped kink. Still a
   * plain weighted sum of smooth (C-infinity) sine curves throughout, so
   * the whole path stays exactly as kink-free as the single-sine version
   * it supersedes; only the final `x` gets a hard clamp, as a defensive
   * floor against the wobble ripple nudging it past the column edge at the
   * widest part of the loop band. */
  function rawPointAtY(y: number): { x: number; y: number } {
    const ramp = smoothstep(LOOP_START_Y, LOOP_START_Y + LOOP_RAMP_PX, y);
    const amplitude = baseAmplitude + (loopAmplitude - baseAmplitude) * ramp;
    const gentle = Math.sin((Math.PI * y) / SERPENTINE_BAND_HEIGHT_PX);
    const tight = Math.sin((Math.PI * y) / loopPeriod);
    const primary = gentle * (1 - ramp) + tight * ramp;
    const secondary = Math.sin(
      (Math.PI * y) / (SERPENTINE_BAND_HEIGHT_PX * secondaryPeriodMul) + secondaryPhase
    );
    const baseX = centreX + amplitude * (primary * 0.72 + secondary * 0.28);
    const wobble = WOBBLE_AMPLITUDE * Math.sin(WOBBLE_K * y + seed);
    const x = Math.min(clampMax, Math.max(clampMin, baseX + wobble));
    return { x, y };
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
