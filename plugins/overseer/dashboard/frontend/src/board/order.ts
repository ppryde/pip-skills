/**
 * Neighbour-midpoint order helper for drag-drop (see wf005-context.md
 * "Order-value computation" and the C4 brief). No client-side renumbering —
 * an integer midpoint can collide with a tight-packed neighbour's own order;
 * that tie is TOLERATED (layout.ts's lane sort tiebreaks on `id`). This is a
 * documented known limitation, not a bug.
 */
import type { BoardCard } from "../api/types";

/**
 * `laneCards` must already be sorted by `order` ascending, and must NOT
 * include the card being dropped (callers filter the dragged card out before
 * calling this — see dragPlan.ts). `toIndex` is the index the dragged card
 * should land at within that (dragged-card-excluded) list.
 */
export function orderForDrop(laneCards: BoardCard[], toIndex: number): number {
  if (laneCards.length === 0) return 0;

  const above = toIndex > 0 ? laneCards[toIndex - 1] : undefined;
  const below = toIndex < laneCards.length ? laneCards[toIndex] : undefined;

  if (above && below) return Math.floor((above.order + below.order) / 2);
  if (below) return below.order - 10; // dropping before the first card
  if (above) return above.order + 10; // dropping after the last card
  return 0; // unreachable given the length check above, but keeps TS happy
}
