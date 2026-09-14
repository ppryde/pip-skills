import type { AlmonerItem, AlmonerSource } from "../../api/types";

/**
 * Shaping a digest for display: which group a row belongs in, and in what
 * order rows sit inside it.
 *
 * Grouped by URGENCY, never by source — one merged view is the whole point
 * of the page, and a reader who wanted three inboxes already has three.
 *
 * Nothing here judges. `awaiting` arrives already computed by the CLI (the
 * last message in the conversation is not yours), deliberately on the CLI
 * side of the boundary so the connector-backed and token-backed transports
 * cannot drift apart in behaviour. This module only arranges what it is given.
 */

export type DigestGroupKey = "awaiting" | "reconcile" | "fyi";

export interface DigestGroup {
  key: DigestGroupKey;
  label: string;
  items: AlmonerItem[];
}

/** Fixed display order. `reconcile` sits below `awaiting` because nobody sent
 * a reconcile item — it is derived by joining two sources, has no arrival
 * time, and must not compete with things a person actually said to you. */
const GROUPS: { key: DigestGroupKey; label: string }[] = [
  { key: "awaiting", label: "Awaiting you" },
  { key: "reconcile", label: "Reconcile" },
  { key: "fyi", label: "For information" },
];

function groupKeyFor(item: AlmonerItem): DigestGroupKey {
  if (item.asks === "reconcile") return "reconcile";
  // Strictly `=== true`: an adapter that cannot compute the rule leaves the
  // field absent, and absence must not manufacture urgency.
  return item.awaiting === true ? "awaiting" : "fyi";
}

/** `arrived` as epoch ms, or null when absent or unparseable. A bad date
 * sorts as undated rather than poisoning the comparator with NaN. */
function arrivedMs(item: AlmonerItem): number | null {
  if (!item.arrived) return null;
  const ms = Date.parse(item.arrived);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Ranked items first, ascending — the judging pass has an opinion and it wins.
 * Everything else falls back to newest-first, which is what an unranked digest
 * can honestly offer. That fallback is the boundary test from the design: pull
 * the skill out and the page still reads usefully, just unsorted by need.
 */
function byNeed(a: AlmonerItem, b: AlmonerItem): number {
  const [ar, br] = [a.rank ?? null, b.rank ?? null];
  if (ar !== null && br !== null) return ar - br;
  if (ar !== null) return -1;
  if (br !== null) return 1;

  const [am, bm] = [arrivedMs(a), arrivedMs(b)];
  if (am !== null && bm !== null) return bm - am;
  if (am !== null) return -1;
  if (bm !== null) return 1;
  return 0;
}

/** The digest as display groups, empty groups omitted. Sort is stable, so
 * rows the comparator cannot separate keep the order the CLI sent them. */
export function groupDigest(items: AlmonerItem[]): DigestGroup[] {
  return GROUPS.map(({ key, label }) => ({
    key,
    label,
    items: items.filter((item) => groupKeyFor(item) === key).sort(byNeed),
  })).filter((group) => group.items.length > 0);
}

/** Labels of sources this refresh could not reach. The page names these
 * explicitly: a silently short digest is worse than a visible error, because
 * an empty list reads as "nothing needs you" either way. */
export function failedSources(sources: AlmonerSource[] | undefined): string[] {
  return (sources ?? []).filter((source) => !source.ok).map((source) => source.label);
}

/**
 * How long ago something arrived, as a compact label ("3h", "2d").
 *
 * Returns "" for an absent or unparseable timestamp — derived reconcile
 * items have no arrival time at all, and the caller renders nothing rather
 * than "Invalid Date". A future timestamp (clock skew between providers is
 * real, and the design already allows for it) clamps to "now".
 */
export function relativeArrived(arrived: string | undefined, now: number = Date.now()): string {
  if (!arrived) return "";
  const ms = Date.parse(arrived);
  if (Number.isNaN(ms)) return "";
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

/**
 * `relativeArrived` as a full phrase — "3h ago", "just now" — so a caller
 * that appends " ago" itself doesn't have to special-case the "now" bucket
 * to avoid rendering "gathered now ago". Empty input still yields "", so a
 * caller composing a longer sentence around it can tell "nothing to report"
 * apart from "just happened" and omit the sentence entirely rather than
 * printing something like "Most recent arrival  ago." with the gap where a
 * duration should be.
 */
export function relativeArrivedPhrase(arrived: string | undefined, now: number = Date.now()): string {
  const rel = relativeArrived(arrived, now);
  if (rel === "") return "";
  return rel === "now" ? "just now" : `${rel} ago`;
}

export type RowStateKey = "open" | "reconcile" | "settled" | "bundled";

export interface RowState {
  key: RowStateKey;
  /** The words on the state chip. It says what it means, so the colour is
   * reinforcement rather than the only channel carrying it. */
  label: string;
}

/**
 * The state a table row wears: its left-edge spine colour and its chip.
 *
 * Deliberately the same three-way split as `groupDigest`'s groups — the
 * table and the grouped view must never disagree about what a row is, only
 * about where it sits.
 */
export function rowState(item: AlmonerItem): RowState {
  if (item.asks === "reconcile") return { key: "reconcile", label: "reconcile" };
  // Checked before `awaiting`: a rollup of machine mail is never awaiting a
  // reply, whatever the adapter happened to set.
  if (item.bundled === true) return { key: "bundled", label: "bundled" };
  if (item.awaiting === true) return { key: "open", label: "needs you" };
  return { key: "settled", label: "settled" };
}
