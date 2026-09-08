import { describe, expect, it } from "vitest";

import { reorderLaneIds } from "./laneOrder";
import type { BoardCard } from "../api/types";

function card(over: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    title: over.id,
    status: "planned",
    stage: null,
    parent: null,
    is_epic: false,
    order: 0,
    created: "2026-07-01T09:00",
    updated: "2026-07-01T09:00",
    ...over,
  } as BoardCard;
}

const A = card({ id: "A" });
const B = card({ id: "B" });
const C = card({ id: "C" });

describe("reorderLaneIds — a flat lane", () => {
  it("moves a card forward to the index it was dropped on", () => {
    expect(reorderLaneIds([A, B, C], "A", 2)).toEqual(["B", "C", "A"]);
  });

  it("moves a card backward", () => {
    expect(reorderLaneIds([A, B, C], "C", 0)).toEqual(["C", "A", "B"]);
  });

  it("sends a card to the end for a drop on the lane's own background", () => {
    // `locateDropTarget` reports `cards.length` for a background drop.
    expect(reorderLaneIds([A, B, C], "A", 3)).toEqual(["B", "C", "A"]);
  });

  it("returns null when the drop changes nothing, so no write is issued", () => {
    expect(reorderLaneIds([A, B, C], "A", 0)).toBeNull();
  });

  it("returns null for a card that is not in this lane", () => {
    expect(reorderLaneIds([A, B, C], "ZZ", 1)).toBeNull();
  });
});

describe("reorderLaneIds — epic groups", () => {
  // `sortLane` renders a group as [root, ...same-lane children] contiguously
  // and will REGROUP whatever id order it is handed, so a naive array-move
  // over the flattened list can stamp an order it then refuses to reproduce.
  const epic = card({ id: "E", is_epic: true });
  const kid1 = card({ id: "E1", parent: "E" });
  const kid2 = card({ id: "E2", parent: "E" });
  const lone = card({ id: "L" });
  const lane = [epic, kid1, kid2, lone];

  it("moves a whole group when its root is dragged, keeping the run contiguous", () => {
    expect(reorderLaneIds(lane, "E", 3)).toEqual(["L", "E", "E1", "E2"]);
  });

  it("moves the whole group when a CHILD is dragged out of it", () => {
    // A child dropped past the group's end cannot lead the lane on its own —
    // it is still its parent's child, so `sortLane` would fold it straight
    // back. Moving the group is the honest reading of that drag.
    expect(reorderLaneIds(lane, "E1", 3)).toEqual(["L", "E", "E1", "E2"]);
  });

  it("reorders siblings when a child is dragged WITHIN its own group", () => {
    expect(reorderLaneIds(lane, "E2", 1)).toEqual(["E", "E2", "E1", "L"]);
  });

  it("refuses to displace a group's root from the front of its own run", () => {
    // The root carries the group's position in the lane; there is nowhere
    // inside the run for it to go.
    expect(reorderLaneIds(lane, "E", 1)).toBeNull();
  });

  it("produces an order sortLane reproduces — the whole contract", () => {
    // Every id appears exactly once, and each group's cards stay adjacent
    // with the root leading, which is precisely what `sortLane` rebuilds.
    const ids = reorderLaneIds(lane, "L", 0)!;
    expect(ids).toEqual(["L", "E", "E1", "E2"]);
    expect(new Set(ids).size).toBe(lane.length);
  });
});
