/**
 * Turning a same-lane drag into the id list `overseer reorder` should stamp.
 *
 * Pure and DOM-free, like `dragPlan.ts` — `resolveDrop` is the only caller.
 *
 * The hard part is epics. `sortLane` renders a lane as contiguous GROUPS —
 * a root card followed by its same-lane descendants — and it will regroup
 * whatever id order it is handed. So a naive array-move over the flattened
 * list can stamp an order that `sortLane` then refuses to reproduce: drag an
 * epic's child to the top of the lane and it is still that epic's child, so
 * it folds straight back under its parent and appears not to have moved. The
 * fix is to move at the granularity the sort actually honours:
 *
 * - dragging a card into a DIFFERENT group moves its whole group, keeping
 *   the run contiguous — which is what the reader sees anyway, since a group
 *   cannot be split on screen.
 * - dragging a card WITHIN its own group reorders it among its siblings
 *   (children are ranked by `compareOrder`), leaving the root at the front.
 *
 * Both cases flatten to an id list that `sortLane` reproduces exactly, which
 * is the whole contract: what you stamp is what you get back after the poll.
 */
import type { BoardCard } from "../api/types";

interface Group {
  cards: BoardCard[];
}

/** Splits a lane's already-flattened cards back into their groups. Relies on
 * `sortLane`'s guarantee that a group is contiguous and root-first — a card
 * whose parent is present in this lane continues the group being built,
 * anything else starts a new one. */
function toGroups(cards: BoardCard[]): Group[] {
  const idsInLane = new Set(cards.map((c) => c.id));
  const groups: Group[] = [];
  for (const card of cards) {
    const isChild = card.parent != null && idsInLane.has(card.parent);
    if (isChild && groups.length > 0) groups[groups.length - 1].cards.push(card);
    else groups.push({ cards: [card] });
  }
  return groups;
}

/** Standard drag move: pull `from` out, put it back at `to`. */
function arrayMove<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/**
 * The lane's ids in their post-drop order, or `null` when the drop changes
 * nothing and there is no point writing.
 *
 * `cards` is the lane's CURRENT flattened order (including the dragged
 * card); `toIndex` is the index within it that the drop landed on, as
 * `locateDropTarget` reports it — `cards.length` for a drop on the lane's
 * own background, meaning "the end".
 */
export function reorderLaneIds(
  cards: BoardCard[],
  draggedId: string,
  toIndex: number
): string[] | null {
  const fromIndex = cards.findIndex((c) => c.id === draggedId);
  if (fromIndex === -1) return null;

  const groups = toGroups(cards);
  // Which group each flattened index belongs to, so a card index and a drop
  // index can both be resolved without re-walking the parent links.
  const groupOfIndex: number[] = [];
  groups.forEach((g, gi) => g.cards.forEach(() => groupOfIndex.push(gi)));

  const fromGroup = groupOfIndex[fromIndex];
  // A background drop (`toIndex === cards.length`) has no group of its own —
  // it means "after the last one", so it resolves to the final group.
  const toGroup =
    toIndex >= cards.length ? groups.length - 1 : groupOfIndex[toIndex];

  let next: BoardCard[];
  if (fromGroup === toGroup && groups[fromGroup].cards.length > 1) {
    // Within one epic group: reorder the siblings. The root holds the
    // group's position in the lane, so it stays at the front — a drop that
    // would displace it is treated as a move of the whole group instead
    // (handled by the else branch via the root check below).
    const group = groups[fromGroup];
    const base = groupOfIndex.indexOf(fromGroup);
    const localFrom = fromIndex - base;
    const localTo = Math.min(Math.max(toIndex - base, 1), group.cards.length - 1);
    if (localFrom === 0) return null; // dragging the root inside its own group: nowhere to go
    const reordered = arrayMove(group.cards, localFrom, localTo);
    next = groups.flatMap((g, gi) => (gi === fromGroup ? reordered : g.cards));
  } else {
    next = arrayMove(groups, fromGroup, toGroup).flatMap((g) => g.cards);
  }

  const ids = next.map((c) => c.id);
  const before = cards.map((c) => c.id);
  return ids.every((id, i) => id === before[i]) ? null : ids;
}
