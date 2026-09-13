import type { AlmonerItem } from "../../api/types";

/**
 * The day band — arrivals placed along a time axis.
 *
 * It answers one question nothing else on the page does: what shape did the
 * day have? The quiet middle afternoon and the 19:06 pile-up are visible at
 * a glance, and over a fortnight that is an argument about your calendar
 * rather than your inbox.
 *
 * Pure geometry. It computes positions and hands them back; the component
 * draws them and owns every colour.
 */

/** Vertical slots a clustered run of arrivals is spread across. Four is
 * enough to keep a burst legible without the band growing tall. */
export const LANES = 4;

/** Below this fraction of the window, two arrivals would overlap on screen,
 * so the later one is lifted a lane. Derived from the blip being ~11px on a
 * band several hundred wide. */
const CLUSTER_FRACTION = 0.035;

/** A day squeezed into ten minutes would draw every blip on one spot. */
const MIN_SPAN_MS = 4 * 3600_000;

const HOUR_MS = 3600_000;

export interface Blip {
  id: string;
  source: string;
  /** Still awaiting you — drawn with a ring. */
  open: boolean;
  /** 0–100, position across the band. */
  leftPct: number;
  /** 0–(LANES-1), how far the blip is lifted off the axis. */
  lane: number;
}

export interface HourTick {
  ms: number;
  leftPct: number;
  /** "13:00" */
  label: string;
}

export interface DayBand {
  startMs: number;
  endMs: number;
  hours: HourTick[];
  blips: Blip[];
}

function arrivedMs(item: AlmonerItem): number | null {
  if (!item.arrived) return null;
  const ms = Date.parse(item.arrived);
  return Number.isNaN(ms) ? null : ms;
}

function floorHour(ms: number): number {
  const date = new Date(ms);
  date.setMinutes(0, 0, 0);
  return date.getTime();
}

/**
 * Geometry for one day's arrivals, or null when none of them can be placed.
 *
 * Null rather than an empty band on purpose: the band is a picture of when
 * things arrived, and an axis with nothing on it reads as a broken chart
 * rather than as a quiet day.
 */
export function dayBand(items: AlmonerItem[]): DayBand | null {
  const dated = items
    // Rollups are excluded on purpose. They are arrivals, but they are not
    // what the band is asking about: a row standing for four newsletters
    // would plot as one dot of equal weight to a review request, and the
    // picture is meant to show when work reached you, not when mail did.
    .filter((item) => item.bundled !== true)
    .map((item) => ({ item, ms: arrivedMs(item) }))
    .filter((entry): entry is { item: AlmonerItem; ms: number } => entry.ms !== null)
    .sort((a, b) => a.ms - b.ms);

  if (dated.length === 0) return null;

  const startMs = floorHour(dated[0].ms);
  let endMs = floorHour(dated[dated.length - 1].ms) + HOUR_MS;
  if (endMs - startMs < MIN_SPAN_MS) endMs = startMs + MIN_SPAN_MS;
  const span = endMs - startMs;

  const at = (ms: number): number =>
    Math.min(100, Math.max(0, ((ms - startMs) / span) * 100));

  const blips: Blip[] = [];
  let lane = 0;
  let previousMs: number | null = null;
  for (const { item, ms } of dated) {
    // A run of arrivals close together climbs the lanes; an isolated one
    // drops back to the axis, so the band reads as bursts and lulls.
    if (previousMs !== null && (ms - previousMs) / span < CLUSTER_FRACTION) {
      lane = (lane + 1) % LANES;
    } else {
      lane = 0;
    }
    previousMs = ms;
    blips.push({
      id: item.id,
      source: item.source,
      open: item.awaiting === true,
      leftPct: at(ms),
      lane,
    });
  }

  const hours: HourTick[] = [];
  for (let ms = startMs; ms <= endMs; ms += HOUR_MS) {
    hours.push({
      ms,
      leftPct: at(ms),
      label: `${String(new Date(ms).getHours()).padStart(2, "0")}:00`,
    });
  }

  return { startMs, endMs, hours, blips };
}
