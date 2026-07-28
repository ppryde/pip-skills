import type { BoardCard } from "../api/types";

/** Sum of `budget.actual` across all cards — HANDOFF's top-bar "Gold total"
 * pill. Actuals only (not estimates): gold is tokens actually spent. */
export function goldTotal(cards: BoardCard[]): number {
  return cards.reduce((sum, c) => sum + c.budget.actual, 0);
}
