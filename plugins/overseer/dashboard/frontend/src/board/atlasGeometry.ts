/**
 * Pure date/SVG math for the Epic Atlas campaign-trail view (WF-086). Every
 * function takes `today`/dates explicitly — nothing in this module calls
 * `Date.now()` or bare `new Date()`, so callers control "now" and every
 * function stays trivially testable and re-render-stable.
 *
 * KB-003: the board contract stores `created` as a bare "%Y-%m-%d" (which
 * `new Date(...)` parses as UTC midnight) and `updated` as an ISO-minute
 * "%Y-%m-%dT%H:%M" (which `new Date(...)` parses in the LOCAL timezone).
 * Comparing the two un-normalized skews trail ordering by the runtime's UTC
 * offset. `parseCalendarDate` is the single entrypoint every helper below
 * routes through — it truncates to the calendar-day prefix and always
 * constructs via `Date.UTC`, so a "created" day and an "updated" timestamp
 * on the same calendar day always collapse onto the identical instant.
 */

/** Parses any `created`/`updated`-shaped string to that calendar day's
 * UTC midnight, ignoring any time-of-day component. This is the ONLY
 * place in the module allowed to construct a `Date` from a raw string —
 * every other export takes a `Date` (or routes a string through this).
 *
 * A blank or garbage value falls back to epoch 0, never `NaN` — same
 * blank-tolerant contract as `layout.ts`'s `parseRecency` (KB-013). An
 * un-guarded `NaN` here would poison every downstream computation that
 * touches it (`computeWindow`'s `span <= 0` guard doesn't catch `NaN` —
 * `NaN <= 0` is `false`), corrupting the whole shared axis from one bad
 * card. `computeWindow` additionally treats this epoch sentinel as "no
 * signal" and excludes it from its min/max aggregation, so the bad card
 * degrades only its own row, never every other row's shared window. */
export function parseCalendarDate(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  const parsed = Date.UTC(y, m - 1, d);
  return new Date(Number.isNaN(parsed) ? 0 : parsed);
}

export interface AtlasWindow {
  start: Date;
  end: Date;
}

/** Minimal shape `computeWindow` needs from an epic — real callers pass
 * board cards (which satisfy this structurally). `children` carries only
 * the done waypoints' `updated` dates the trail actually plots. */
export interface WindowEpic {
  created: string;
  /** The epic's own `updated` — the walked-trail end for a parked epic
   * with no children, or any epic with none done yet. */
  updated: string;
  children?: { updated: string }[];
}

const WINDOW_PAD_MS = 2 * 86400000;

/** The atlas's shared date axis: min(epic created) .. max(today, every
 * child's updated), padded ~2 days each side so trailheads/beasts never
 * sit flush against the chart edge. Never crashes on an empty epic list —
 * falls back to a window centred on `today` so an empty board still
 * renders a sane (if empty) axis. */
export function computeWindow(epics: WindowEpic[], today: Date): AtlasWindow {
  if (epics.length === 0) {
    return {
      start: new Date(today.getTime() - WINDOW_PAD_MS),
      end: new Date(today.getTime() + WINDOW_PAD_MS),
    };
  }

  let minCreated = Infinity;
  let maxUpdated = today.getTime();

  // `parseCalendarDate`'s epoch-0 fallback (blank/garbage input) is a
  // sentinel for "no signal", not a real 1970 date — feeding it into
  // Math.min/max would let one malformed card's epoch reading win against
  // every genuine 2020s+ card date and drag the whole shared axis back to
  // 1970. Skipping it here is what actually confines a bad card's damage
  // to its own row instead of every row's shared window.
  const isRealSignal = (ms: number) => ms !== 0;

  for (const epic of epics) {
    const createdMs = parseCalendarDate(epic.created).getTime();
    if (isRealSignal(createdMs)) minCreated = Math.min(minCreated, createdMs);

    const updatedMs = parseCalendarDate(epic.updated).getTime();
    if (isRealSignal(updatedMs)) maxUpdated = Math.max(maxUpdated, updatedMs);

    for (const child of epic.children ?? []) {
      const childMs = parseCalendarDate(child.updated).getTime();
      if (isRealSignal(childMs)) maxUpdated = Math.max(maxUpdated, childMs);
    }
  }

  // Every epic's `created` was invalid — nothing real left to anchor the
  // window's start, so fall back to the same "centred on today" treatment
  // as the empty-epic-list branch above, rather than leaving `Infinity`
  // to poison the subtraction below into `-Infinity`.
  if (minCreated === Infinity) minCreated = today.getTime();

  return {
    start: new Date(minCreated - WINDOW_PAD_MS),
    end: new Date(maxUpdated + WINDOW_PAD_MS),
  };
}

/** Maps `date` onto the window's 0–100 horizontal axis. A zero-length
 * window (defensive only — `computeWindow` always pads) reports 0 rather
 * than dividing by zero. `!(span > 0)` (not `span <= 0`) is deliberate: a
 * `NaN` span (an Invalid Date on either end of `window`) fails BOTH
 * comparisons — `NaN <= 0` and `NaN > 0` are both `false` in JS — so
 * `span <= 0` alone silently falls through to the division below and
 * returns `NaN`, which then poisons every SVG x/y/cx/cy attribute a
 * caller computes from it (React logs "Received NaN for the ... attribute"
 * for each one). `computeWindow` (this module) already keeps its OWN
 * output NaN-free, but `pctForDate` is exported and callers such as
 * AtlasTrail take a `window` prop directly — this guard makes the
 * function itself safe regardless of how well-behaved its caller is. */
export function pctForDate(date: Date, window: AtlasWindow): number {
  const span = window.end.getTime() - window.start.getTime();
  if (!(span > 0)) return 0;
  return ((date.getTime() - window.start.getTime()) / span) * 100;
}

const WEEK_MS = 7 * 86400000;

/** Weekly tick marks across the window, starting exactly at `window.start`
 * and never overshooting `window.end` — a window whose span isn't a whole
 * number of weeks simply gets fewer ticks, not a dangling last one past
 * the axis. */
export function computeAxisTicks(window: AtlasWindow): Date[] {
  const ticks: Date[] = [];
  for (let t = window.start.getTime(); t <= window.end.getTime(); t += WEEK_MS) {
    ticks.push(new Date(t));
  }
  return ticks;
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
 * neighbours, deterministically (no storage, stable across renders). */
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

const FALLBACK_PACE_MS = 5 * 86400000;

/**
 * Pace-projects the "uncharted ground" ahead of the walked trail: elapsed
 * time ÷ quests done gives a days/quest pace, multiplied by quests
 * remaining. Zero done quests have no pace to measure, so they fall back
 * to a ~5 day/quest guess (matches the prototype). The ledger keeps no due
 * dates, so this is explicitly flavour — always clamped inside
 * [walkedEndDate, windowEnd] so it can never draw off the chart or
 * backwards past where the party actually stands.
 */
export function projectedEnd(
  startDate: Date,
  walkedEndDate: Date,
  done: number,
  total: number,
  windowEnd: Date
): Date {
  const pace = done > 0 ? (walkedEndDate.getTime() - startDate.getTime()) / done : FALLBACK_PACE_MS;
  // `total - done || 2` would treat a LEGITIMATE zero (every quest done,
  // epic just not yet marked done) the same as the empty-epic fallback
  // sentinel — `0 || 2` is truthy-coerced to 2, projecting phantom
  // uncharted ground past a fully-cleared trail. Only an actually-empty
  // epic (no quests to ever have "remaining") gets the 2-quest guess.
  const remaining = total > 0 ? total - done : 2;
  const projected = walkedEndDate.getTime() + pace * remaining;
  // Ceiling first (never past the window), then floor (never before the
  // walked end) — the floor wins if a pathological windowEnd predates
  // walkedEndDate, since walked history is a hard fact and windowEnd here
  // is just axis padding.
  const clamped = Math.max(walkedEndDate.getTime(), Math.min(projected, windowEnd.getTime()));
  return new Date(clamped);
}

/** "4 AUG" style stamp — en-GB day + short month, uppercase. Formats in
 * UTC explicitly (never the runtime's local zone) so a UTC-midnight date
 * from `parseCalendarDate` can never roll back a day on display. */
export function formatDateStamp(date: Date): string {
  return date
    .toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })
    .toUpperCase();
}
