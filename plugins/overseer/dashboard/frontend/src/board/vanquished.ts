import type { BoardCard } from "../api/types";

export interface VanquishedStats {
  done: number;
  total: number;
}

/** Done-count / total-count — HANDOFF's "N / M vanquished" top-bar pill. */
export function vanquishedStats(cards: BoardCard[]): VanquishedStats {
  return {
    done: cards.filter((c) => c.status === "done").length,
    total: cards.length,
  };
}
