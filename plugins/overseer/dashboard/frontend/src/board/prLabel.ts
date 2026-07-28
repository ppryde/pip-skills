import type { PrWindow } from "../api/types";

/**
 * "PR #{number} · {review_state}" — the number and review-state segments
 * each appear only when present, mirroring the pre-WF-042 top-bar PR pill's
 * own formatting. WF-042 moved this onto the Party's per-agent hero cards/
 * rows (`session.pr`) instead of the single launching-session pill.
 */
export function prLabel(pr: PrWindow): string {
  const number = pr.number !== undefined ? ` #${pr.number}` : "";
  const state = pr.review_state ? ` · ${pr.review_state}` : "";
  return `PR${number}${state}`;
}
