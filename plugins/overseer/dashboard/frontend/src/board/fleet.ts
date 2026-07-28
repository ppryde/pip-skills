import type { SessionSummary } from "../api/types";

export interface FleetSummary {
  /** Live (non-stale) session count — a stale session isn't currently out
   * on a quest, it's just a ghost still shown in the Party (mirrors
   * TopBar's prior questing-pill count, see party.ts). */
  questing: number;
  /** Max `pct` across live sessions that carry one; `null` when no live
   * session has a pct (never NaN). */
  topCtx: number | null;
  /** Count of live sessions at/over `threshold`; `0` when `threshold` is
   * `null` — no threshold means nothing can be "near" it. */
  nearThreshold: number;
}

/**
 * WF-042: fleet-health summary for the top bar, replacing the single
 * launching-session ctx%/model/PR readout. Pure/testable — drops stale
 * sessions, tolerates missing `pct`, and is safe with an empty fleet or a
 * `null` threshold (no NaN, ever).
 */
export function fleetSummary(
  sessions: SessionSummary[],
  threshold: number | null
): FleetSummary {
  const live = sessions.filter((s) => !s.stale);

  const livePcts = live
    .map((s) => s.pct)
    .filter((pct): pct is number => pct !== undefined);
  const topCtx = livePcts.length > 0 ? Math.max(...livePcts) : null;

  const nearThreshold =
    threshold === null
      ? 0
      : live.filter((s) => s.pct !== undefined && s.pct >= threshold).length;

  return {
    questing: live.length,
    topCtx,
    nearThreshold,
  };
}
