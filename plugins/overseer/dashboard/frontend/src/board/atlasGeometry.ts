/**
 * Small shared primitives for the Epic Atlas (WF-086). v1's date-axis
 * machinery (`computeWindow`, `pctForDate`, `computeAxisTicks`,
 * `projectedEnd`) is KILLED by the v2 progress-trail revision — see
 * `docs/design/epic-atlas/HANDOFF.md`'s "Killed from v1" section. Trail
 * position is now driven entirely by cumulative child COMPLEXITY, not
 * dates (see `board/atlasTrailLayout.ts`). What survives here:
 * `parseCalendarDate`/`formatDateStamp` (tooltip/checklist date stamps
 * only) and `wobblePath`/`seedFor` (the hand-drawn line character).
 */

/** Parses any `created`/`updated`-shaped string to that calendar day's
 * UTC midnight, ignoring any time-of-day component. This is the ONLY
 * place in the module allowed to construct a `Date` from a raw string —
 * every other export takes a `Date` (or routes a string through this).
 *
 * A blank or garbage value falls back to epoch 0, never `NaN` — same
 * blank-tolerant contract as `layout.ts`'s `parseRecency` (KB-013).
 *
 * KB-003: the board contract stores `created` as a bare "%Y-%m-%d" (which
 * `new Date(...)` parses as UTC midnight) and `updated` as an ISO-minute
 * "%Y-%m-%dT%H:%M" (which `new Date(...)` parses in the LOCAL timezone).
 * Comparing the two un-normalized skews trail/tooltip ordering by the
 * runtime's UTC offset — this is the single entrypoint every date-facing
 * helper routes through to avoid that. */
export function parseCalendarDate(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  const parsed = Date.UTC(y, m - 1, d);
  return new Date(Number.isNaN(parsed) ? 0 : parsed);
}

const WOBBLE_AMPLITUDE = 12;
/** Wavelength ~300px, ported from the prototype's `k = 0.02` (the exact
 * 2π/300 this approximates) so per-row phase seeds line up with the
 * design reference's hand-drawn cadence. */
const WOBBLE_K = (2 * Math.PI) / 300;

export interface WobblePath {
  d: string;
  yAt: (x: number) => number;
}

/** Gentle hand-wobbled sine trail between `x0`..`x1` down the lane, ported
 * from the prototype's `trail()`. `seed` phase-shifts the sine so adjacent
 * rows never wobble in lockstep — see `seedFor`. */
export function wobblePath(x0: number, x1: number, laneHeight: number, seed: number): WobblePath {
  const y = laneHeight * 0.52;
  const yAt = (x: number) => y + WOBBLE_AMPLITUDE * Math.sin(WOBBLE_K * x + seed);

  const steps = Math.max(2, Math.round((x1 - x0) / 14));
  let d = "";
  for (let i = 0; i <= steps; i++) {
    const x = x0 + (x1 - x0) * (i / steps);
    d += (i ? " L" : "M") + x.toFixed(1) + " " + yAt(x).toFixed(1);
  }

  return { d, yAt };
}

/** djb2 hash — same pattern as `labelColor.ts`/`beastName.ts` — folded
 * into a 0..2π phase so each epic's trail wobbles out of sync with its
 * neighbours, deterministically (no storage, stable across renders). Being
 * keyed on the card's own id (not its array index) is what makes toggling
 * the vanquished-epics filter/sort never re-wobble a surviving trail — see
 * HANDOFF's toolbar section. */
function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = (h * 33 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

export function seedFor(cardId: string): number {
  return ((hashString(cardId) % 1000) / 1000) * Math.PI * 2;
}

/** "4 AUG" style stamp — en-GB day + short month, uppercase. Formats in
 * UTC explicitly (never the runtime's local zone) so a UTC-midnight date
 * from `parseCalendarDate` can never roll back a day on display. */
export function formatDateStamp(date: Date): string {
  return date
    .toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })
    .toUpperCase();
}
