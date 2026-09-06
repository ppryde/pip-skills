/**
 * Distinct branch names across cards and sessions (WF-031 branch filter) —
 * the union that seeds `BranchFilter`'s options and, via App.tsx, drives the
 * board's dim/spotlight treatment. Case-sensitive exact-string dedupe;
 * empty/undefined branches are dropped rather than surfacing a spurious
 * blank option.
 *
 * Ordered by recency: a branch a session has worked on lists by that
 * session's latest activity, newest first, so the branch you were just on
 * is at the top of the menu. Branches only cards carry (no session seen)
 * follow, alphabetically — a card has no activity clock of its own.
 */
import type { BoardCard, SessionSummary } from "../api/types";

/** A session's activity instant as a number; malformed/missing reads as 0. */
export function sessionActiveTs(session: SessionSummary): number {
  for (const raw of [session.active_at, session.updated_at]) {
    const n = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : NaN;
    if (Number.isFinite(n) && n > 0) return n;
  }
  return 0;
}

/** Sort branch names by the newest activity each has seen, newest first;
 * ties and never-active branches (0) alphabetical. Shared with the
 * Chronicle's branch list, which derives its own activity map. */
export function orderBranchesByActivity(activity: Map<string, number>): string[] {
  return [...activity.entries()]
    .sort(([a, ta], [b, tb]) => tb - ta || a.localeCompare(b))
    .map(([name]) => name);
}

export function distinctBranches(cards: BoardCard[], sessions: SessionSummary[]): string[] {
  const activity = new Map<string, number>();
  for (const session of sessions) {
    if (!session.branch) continue;
    activity.set(session.branch, Math.max(activity.get(session.branch) ?? 0, sessionActiveTs(session)));
  }
  for (const card of cards) {
    if (card.branch && !activity.has(card.branch)) activity.set(card.branch, 0);
  }
  return orderBranchesByActivity(activity);
}
