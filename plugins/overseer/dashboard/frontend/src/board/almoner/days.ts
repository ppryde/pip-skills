import type { AlmonerItem } from "../../api/types";

/**
 * The digest cut into days.
 *
 * Time is the structure of the table view — "yesterday" is the next block
 * down rather than a different screen, which is the whole reason the table
 * doubles as the history view.
 */

export interface DigestDay {
  /** Stable key — the local calendar date, `YYYY-MM-DD`. */
  key: string;
  /** "Today · Saturday 13 September" */
  label: string;
  items: AlmonerItem[];
}

function arrivedMs(item: AlmonerItem): number | null {
  if (!item.arrived) return null;
  const ms = Date.parse(item.arrived);
  return Number.isNaN(ms) ? null : ms;
}

/** Local calendar date key, so a 23:50 message belongs to the day the reader
 * lived through rather than to UTC's idea of it. */
function dayKey(ms: number): string {
  const date = new Date(ms);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${String(date.getDate()).padStart(2, "0")}`;
}

function labelFor(key: string, now: number): string {
  const todayKey = dayKey(now);
  const yesterdayKey = dayKey(now - 86_400_000);
  const [year, month, day] = key.split("-").map(Number);
  // Named outright rather than "4 days ago": relative counts past yesterday
  // make the reader do arithmetic to place a meeting.
  const named = new Date(year, month - 1, day).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  if (key === todayKey) return `Today · ${named}`;
  if (key === yesterdayKey) return `Yesterday · ${named}`;
  return named;
}

/**
 * Days newest-first, items newest-first within each.
 *
 * Undated items — the derived reconcile checks, which nobody sent — ride at
 * the top of the newest day rather than in a group of their own: they are
 * current, and an orphan "no date" heading reads as a rendering fault rather
 * than as a finding.
 */
export function groupByDay(items: AlmonerItem[], now: number = Date.now()): DigestDay[] {
  if (items.length === 0) return [];

  const undated: AlmonerItem[] = [];
  const byDay = new Map<string, AlmonerItem[]>();

  for (const item of items) {
    const ms = arrivedMs(item);
    if (ms === null) {
      undated.push(item);
      continue;
    }
    const key = dayKey(ms);
    const existing = byDay.get(key);
    if (existing) existing.push(item);
    else byDay.set(key, [item]);
  }

  const days: DigestDay[] = [...byDay.entries()]
    .map(([key, dayItems]) => ({
      key,
      label: labelFor(key, now),
      items: dayItems.sort((a, b) => (arrivedMs(b) ?? 0) - (arrivedMs(a) ?? 0)),
    }))
    .sort((a, b) => (a.key < b.key ? 1 : -1));

  if (undated.length > 0) {
    const newestKey = dayKey(now);
    const newest = days[0];
    // A digest of nothing but undated items still needs a day to sit in.
    if (newest && newest.key >= newestKey) newest.items = [...undated, ...newest.items];
    else days.unshift({ key: newestKey, label: labelFor(newestKey, now), items: undated });
  }

  return days;
}

/** "19:06" — the wall-clock time a row arrived, in the reader's own zone.
 * Empty when there is nothing to show, so an undated row renders no stamp
 * rather than "Invalid Date". */
export function clockTime(arrived: string | undefined): string {
  if (!arrived) return "";
  const ms = Date.parse(arrived);
  if (Number.isNaN(ms)) return "";
  const date = new Date(ms);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
