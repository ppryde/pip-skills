import type { BoardCard } from "../api/types";

/** Groups every card that has a `parent` under that parent id, preserving
 * input order. Parents with no children get no entry (so `.has(id)` is a
 * cheap "does this epic have children" check). Pure — no board knowledge
 * beyond the `parent` field. */
export function groupChildrenByEpic(cards: BoardCard[]): Map<string, BoardCard[]> {
  const byParent = new Map<string, BoardCard[]>();
  for (const c of cards) {
    if (c.parent == null) continue;
    const list = byParent.get(c.parent);
    if (list) list.push(c);
    else byParent.set(c.parent, [c]);
  }
  return byParent;
}
