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
 * every other export takes a `Date` (or routes a string through this). */
export function parseCalendarDate(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
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

  for (const epic of epics) {
    minCreated = Math.min(minCreated, parseCalendarDate(epic.created).getTime());
    maxUpdated = Math.max(maxUpdated, parseCalendarDate(epic.updated).getTime());
    for (const child of epic.children ?? []) {
      maxUpdated = Math.max(maxUpdated, parseCalendarDate(child.updated).getTime());
    }
  }

  return {
    start: new Date(minCreated - WINDOW_PAD_MS),
    end: new Date(maxUpdated + WINDOW_PAD_MS),
  };
}

/** Maps `date` onto the window's 0–100 horizontal axis. A zero-length
 * window (defensive only — `computeWindow` always pads) reports 0 rather
 * than dividing by zero. */
export function pctForDate(date: Date, window: AtlasWindow): number {
  const span = window.end.getTime() - window.start.getTime();
  if (span <= 0) return 0;
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
  const remaining = total - done || 2;
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
