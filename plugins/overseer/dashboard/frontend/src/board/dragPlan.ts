/**
 * Drag-end dispatch decision — kept PURE and unit-testable (no DOM, no
 * dnd-kit types) so the "what calls does this drop map to" logic can be
 * exercised directly. `Board.tsx` is the only caller: it derives
 * `(dragged, targetLane, toIndex, lanes)` from a dnd-kit `DragEndEvent` via
 * `locateDropTarget`, gets a `DropPlan` back from `resolveDrop`, and hands
 * that to `runDropPlan.ts` to actually issue the calls through
 * `useBoard().mutate`.
 *
 * Mirrors wf005-context.md "Drag semantics" / the C4 brief exactly:
 * - within a lane -> setOrder only.
 * - into a stage lane -> move({stage}) THEN setOrder (order matters: mutate
 *   applies whichever response `runDropPlan` returns LAST).
 * - into Parked/Done -> move({status}) only.
 * - into Backlog -> move({status:"planned"}) only, UNLESS the dragged card
 *   still carries a `stage` (a "staged" card) — Backlog refuses that drop
 *   entirely (unblock/park moves never clear `stage` server-side, so
 *   allowing this call would just be a no-op round trip).
 * - only `planned` / non-blocked `in-flight` / `parked` cards are drag
 *   sources at all; everything else resolves to an empty plan defensively.
 */
import type { BoardCard, Stage, Status } from "../api/types";
import type { Lane } from "./layout";
import { orderForDrop } from "./order";

export type DragCall =
  | { kind: "setOrder"; id: string; order: number }
  | { kind: "move"; id: string; body: { stage: Stage } | { status: Status } };

export interface DropPlan {
  calls: DragCall[];
}

const NO_OP: DropPlan = { calls: [] };

/** Only planned / non-blocked in-flight / parked cards may be dragged. */
export function isDragSource(card: BoardCard): boolean {
  return (
    card.status === "planned" ||
    card.status === "in-flight" ||
    card.status === "parked"
  );
}

/**
 * Maps a dnd-kit `over.id` to the lane + index it represents:
 * - if `overId` matches a lane's own droppable id (dropped on the lane's
 *   background, e.g. an empty lane) -> that lane, appended at the end.
 * - if `overId` matches a card id -> that card's lane, at that card's index.
 * - otherwise -> no lane (caller should no-op).
 */
export function locateDropTarget(
  overId: string,
  lanes: Lane[]
): { lane: Lane | undefined; index: number } {
  const directLane = lanes.find((l) => l.key === overId);
  if (directLane) return { lane: directLane, index: directLane.cards.length };

  for (const lane of lanes) {
    const idx = lane.cards.findIndex((c) => c.id === overId);
    if (idx !== -1) return { lane, index: idx };
  }

  return { lane: undefined, index: 0 };
}

/**
 * Decides what call(s) a drop maps to. `lanes` is the CURRENT board layout
 * (before this drop is applied) — used only to find the dragged card's
 * source lane, so we can tell a pure reorder (same lane) apart from a
 * cross-lane move.
 *
 * `toIndex` is the target index in the FULL pre-drop `targetLane.cards` (the
 * value `locateDropTarget` returns — the index of the card the drop landed
 * on, or `cards.length` for a lane-background drop). It still INCLUDES the
 * dragged card when the drop is a same-lane reorder, so we adjust for the
 * dragged card's own removal before computing the neighbour midpoint (see
 * the same-lane branch).
 */
export function resolveDrop(
  dragged: BoardCard,
  targetLane: Lane,
  toIndex: number,
  lanes: Lane[]
): DropPlan {
  if (!isDragSource(dragged)) return NO_OP;

  const sourceLane = lanes.find((l) => l.cards.some((c) => c.id === dragged.id));
  const destCards = targetLane.cards.filter((c) => c.id !== dragged.id);

  if (sourceLane && sourceLane.key === targetLane.key) {
    // Pure reorder within the lane the card already lives in.
    //
    // `destCards` has the dragged card filtered out, but `toIndex` was
    // measured against the full lane (which still contained it). On a
    // FORWARD drag (dragged card originally sits BEFORE the drop target),
    // removing it shifts every later index left by one — so we subtract one
    // to keep forward and backward drags symmetric (without this the card
    // lands one slot too far, e.g. [A,B,C] drag A onto C would land AFTER C
    // instead of between B and C).
    const sourceIdx = targetLane.cards.findIndex((c) => c.id === dragged.id);
    const adjustedIndex =
      sourceIdx !== -1 && sourceIdx < toIndex ? toIndex - 1 : toIndex;
    const order = orderForDrop(destCards, adjustedIndex);
    return { calls: [{ kind: "setOrder", id: dragged.id, order }] };
  }

  // Parked cards NEVER leave Parked via drag (binding rule: they reorder
  // within Parked only — handled by the same-lane branch above — and leave
  // via the /unpark menu in C6). Any cross-lane drop of a parked card is
  // refused here before it can fire a move.
  if (dragged.status === "parked") return NO_OP;

  switch (targetLane.kind) {
    case "stage": {
      if (!targetLane.stage) return NO_OP;
      const order = orderForDrop(destCards, toIndex);
      return {
        calls: [
          { kind: "move", id: dragged.id, body: { stage: targetLane.stage } },
          { kind: "setOrder", id: dragged.id, order },
        ],
      };
    }
    case "parked":
      return { calls: [{ kind: "move", id: dragged.id, body: { status: "parked" } }] };
    case "done":
      return { calls: [{ kind: "move", id: dragged.id, body: { status: "done" } }] };
    case "backlog":
      // Refuse a STAGED card as a no-op — unblock/park never clears `stage`
      // server-side, so this would just round-trip without changing anything.
      if (dragged.stage != null) return NO_OP;
      return { calls: [{ kind: "move", id: dragged.id, body: { status: "planned" } }] };
    default:
      // Archive is not a drag drop target (abandoned cards aren't dragged
      // into it by this UI — no documented flow drops a card there).
      return NO_OP;
  }
}
