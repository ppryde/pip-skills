import type { AlmonerItem } from "../../api/types";

/**
 * "Waiting on you" — the digest re-read as a set of obligations to people.
 *
 * The premise: an obligation is owed to someone, not to a piece of software.
 * "Rhona has been waiting two hours" lands in a way "1 unread" never does.
 *
 * This is also where the last-speaker rule stops being a hidden filter and
 * becomes the headline: `clear` is EARNED — you answered last — rather than
 * merely meaning nothing arrived.
 */

export interface WaitingPerson {
  name: string;
  /** For the disc. Uppercased first character of the name. */
  initial: string;
  /** True when at least one of their asks is still awaiting you. */
  owed: boolean;
  /** How long their OLDEST open ask has been waiting; null when nothing
   * datable, and always null for someone who is clear. */
  waitedMs: number | null;
  /** How many of their items are in this digest at all. */
  count: number;
}

function arrivedMs(item: AlmonerItem): number | null {
  if (!item.arrived) return null;
  const ms = Date.parse(item.arrived);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * People in this digest, the owed first and longest-waiting at the front.
 *
 * `cap` keeps the strip a glance rather than a directory: with thirty
 * colleagues an uncapped strip is mostly ghosts. It bites on the CLEARED
 * first — an owed person falling off the strip is the one outcome that would
 * make it a liar, so the sort runs before the slice and owed always sorts up.
 * That makes `cap` a target for the CLEARED tail rather than a hard ceiling
 * on the whole list: every owed person is kept even when there are more of
 * them than `cap`, so the strip can, deliberately, run longer than `cap`
 * entries on a bad day rather than silently drop someone it owes.
 */
export function whosWaiting(
  items: AlmonerItem[],
  now: number = Date.now(),
  cap = 8
): WaitingPerson[] {
  const byName = new Map<string, AlmonerItem[]>();
  for (const item of items) {
    // Derived reconcile checks have no sender — there is nobody to owe.
    if (!item.who || item.asks === "reconcile") continue;
    const existing = byName.get(item.who);
    if (existing) existing.push(item);
    else byName.set(item.who, [item]);
  }

  const people: WaitingPerson[] = [];
  for (const [name, theirs] of byName) {
    const open = theirs.filter((item) => item.awaiting === true);
    // Only OPEN asks count towards the wait: a settled thread is not a debt,
    // so a long-closed conversation must not inflate how long someone has
    // been kept waiting.
    const times = open.map(arrivedMs).filter((ms): ms is number => ms !== null);
    people.push({
      name,
      initial: (name.trim()[0] ?? "?").toUpperCase(),
      owed: open.length > 0,
      waitedMs: times.length > 0 ? now - Math.min(...times) : null,
      count: theirs.length,
    });
  }

  people.sort((a, b) => {
    if (a.owed !== b.owed) return a.owed ? -1 : 1;
    // Longest wait first. An owed person with no usable timestamp sorts
    // below those we can time, but still above everyone clear.
    return (b.waitedMs ?? -1) - (a.waitedMs ?? -1);
  });

  // `slice(0, cap)` on the sorted list bit into the OWED end too whenever
  // there were more than `cap` owed people — exactly the outcome the doc
  // comment above says must never happen. Every owed person survives, even
  // past `cap`; only the cleared tail is where truncation is allowed to show,
  // which is what "the cap bites on the cleared first" actually requires.
  const owed = people.filter((person) => person.owed);
  const cleared = people.filter((person) => !person.owed);
  return [...owed, ...cleared.slice(0, Math.max(0, cap - owed.length))];
}

/** "2h", "3d", "just now" — how long someone has been kept waiting.
 * Returns "" when there is nothing to time, so the caller renders no stamp
 * rather than a stamp reading "null". */
export function formatWait(waitedMs: number | null): string {
  if (waitedMs === null) return "";
  const minutes = Math.floor(Math.max(0, waitedMs) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}
