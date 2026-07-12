import { describe, expect, it } from "vitest";
import { groupIntoLanes } from "./layout";
import { isDragSource, locateDropTarget, resolveDrop } from "./dragPlan";
import type { BoardCard } from "../api/types";

function card(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    title: `Title ${overrides.id}`,
    status: "planned",
    stage: null,
    complexity: null,
    priority: null,
    sprint: null,
    parent: null,
    depends_on: [],
    order: 10,
    budget: { estimate: null, actual: 0 },
    is_epic: false,
    ready: true,
    rollup: null,
    checklist: [],
    ...overrides,
  };
}

function laneByKey(lanes: ReturnType<typeof groupIntoLanes>, key: string) {
  const lane = lanes.find((l) => l.key === key);
  if (!lane) throw new Error(`lane ${key} not found`);
  return lane;
}

describe("isDragSource", () => {
  it("planned, non-blocked in-flight, and parked cards are drag sources", () => {
    expect(isDragSource(card({ id: "A", status: "planned" }))).toBe(true);
    expect(
      isDragSource(
        card({ id: "B", status: "in-flight", stage: "implementation" })
      )
    ).toBe(true);
    expect(isDragSource(card({ id: "C", status: "parked" }))).toBe(true);
  });

  it("blocked, done, and abandoned cards are NOT drag sources", () => {
    expect(
      isDragSource(card({ id: "A", status: "blocked", stage: "implementation" }))
    ).toBe(false);
    expect(isDragSource(card({ id: "B", status: "done" }))).toBe(false);
    expect(isDragSource(card({ id: "C", status: "abandoned" }))).toBe(false);
  });
});

describe("resolveDrop", () => {
  it("(a) same-lane FORWARD drag (A onto C in [A,B,C]) lands A BETWEEN B and C — index derived via locateDropTarget, off-by-one guarded", () => {
    const a = card({ id: "WF-A", status: "planned", order: 10 });
    const b = card({ id: "WF-B", status: "planned", order: 20 });
    const c = card({ id: "WF-C", status: "planned", order: 30 });
    const lanes = groupIntoLanes([a, b, c]);

    // Derive toIndex the way Board.tsx does — from the card the drop landed
    // on (C). Its full-lane index is 2; A sits BEFORE it (source index 0),
    // so removing A shifts the target left by one -> destCards [B,C], index
    // 1 -> midpoint(B=20, C=30) = 25 (between B and C), NOT after C.
    const { lane, index } = locateDropTarget("WF-C", lanes);
    const plan = resolveDrop(a, lane!, index, lanes);

    expect(plan.calls).toEqual([{ kind: "setOrder", id: "WF-A", order: 25 }]);
  });

  it("(a) same-lane BACKWARD drag (C onto A in [A,B,C]) lands C BEFORE A — index derived via locateDropTarget", () => {
    const a = card({ id: "WF-A", status: "planned", order: 10 });
    const b = card({ id: "WF-B", status: "planned", order: 20 });
    const c = card({ id: "WF-C", status: "planned", order: 30 });
    const lanes = groupIntoLanes([a, b, c]);

    // C (source index 2) dropped onto A (full-lane index 0). Source is NOT
    // before the target, so no shift -> destCards [A,B], index 0 -> before A
    // = A.order(10) - 10 = 0.
    const { lane, index } = locateDropTarget("WF-A", lanes);
    const plan = resolveDrop(c, lane!, index, lanes);

    expect(plan.calls).toEqual([{ kind: "setOrder", id: "WF-C", order: 0 }]);
  });

  it("(a) same-lane interior reorder (drag C onto B) lands between A and B", () => {
    const a = card({ id: "WF-A", status: "planned", order: 10 });
    const b = card({ id: "WF-B", status: "planned", order: 20 });
    const c = card({ id: "WF-C", status: "planned", order: 30 });
    const lanes = groupIntoLanes([a, b, c]);

    // C (source index 2) onto B (full-lane index 1). Source not before target
    // -> destCards [A,B], index 1 -> midpoint(A=10, B=20) = 15.
    const { lane, index } = locateDropTarget("WF-B", lanes);
    const plan = resolveDrop(c, lane!, index, lanes);

    expect(plan.calls).toEqual([{ kind: "setOrder", id: "WF-C", order: 15 }]);
  });

  it("(b) drop into a stage lane -> move({stage}) THEN setOrder", () => {
    const planned = card({ id: "WF-P", status: "planned", order: 10 });
    const existing = card({
      id: "WF-EXIST",
      status: "in-flight",
      stage: "planning",
      order: 20,
    });
    const lanes = groupIntoLanes([planned, existing]);
    const planningLane = laneByKey(lanes, "stage:planning"); // [existing(20)]

    // Drop `planned` at the end of the planning lane.
    const plan = resolveDrop(planned, planningLane, 1, lanes);

    expect(plan.calls).toEqual([
      { kind: "move", id: "WF-P", body: { stage: "planning" } },
      { kind: "setOrder", id: "WF-P", order: 30 }, // existing.order(20) + 10
    ]);
  });

  it("(c) drop into Parked -> move({status:'parked'})", () => {
    const planned = card({ id: "WF-P", status: "planned" });
    const lanes = groupIntoLanes([planned]);
    const parkedLane = laneByKey(lanes, "parked");

    const plan = resolveDrop(planned, parkedLane, 0, lanes);

    expect(plan.calls).toEqual([
      { kind: "move", id: "WF-P", body: { status: "parked" } },
    ]);
  });

  it("(c) drop into Done -> move({status:'done'})", () => {
    const inFlight = card({
      id: "WF-IF",
      status: "in-flight",
      stage: "verification",
    });
    const lanes = groupIntoLanes([inFlight]);
    const doneLane = laneByKey(lanes, "done");

    const plan = resolveDrop(inFlight, doneLane, 0, lanes);

    expect(plan.calls).toEqual([
      { kind: "move", id: "WF-IF", body: { status: "done" } },
    ]);
  });

  it("a parked card dragged CROSS-LANE is refused (NO_OP) — parked cards leave only via /unpark, never drag", () => {
    // One parked card plus a decoy in each destination lane so the target
    // lanes actually exist and are distinct from Parked.
    const parked = card({ id: "WF-PK", status: "parked", order: 10 });
    const stageOccupant = card({
      id: "WF-STG",
      status: "in-flight",
      stage: "implementation",
      order: 10,
    });
    const doneOccupant = card({ id: "WF-DN", status: "done", order: 10 });
    const lanes = groupIntoLanes([parked, stageOccupant, doneOccupant]);

    // Backlog: previously (wrongly) fired move({status:'planned'}).
    expect(
      resolveDrop(parked, laneByKey(lanes, "backlog"), 0, lanes).calls
    ).toEqual([]);
    // Stage lane: previously (wrongly) fired move({stage}) + setOrder.
    expect(
      resolveDrop(parked, laneByKey(lanes, "stage:implementation"), 0, lanes)
        .calls
    ).toEqual([]);
    // Done: previously (wrongly) fired move({status:'done'}).
    expect(
      resolveDrop(parked, laneByKey(lanes, "done"), 0, lanes).calls
    ).toEqual([]);
  });

  it("(d) dropping a STAGED card into Backlog fires NO call (refused no-op)", () => {
    const staged = card({
      id: "WF-STAGED",
      status: "in-flight",
      stage: "implementation",
    });
    const lanes = groupIntoLanes([staged]);
    const backlogLane = laneByKey(lanes, "backlog");

    const plan = resolveDrop(staged, backlogLane, 0, lanes);

    expect(plan.calls).toEqual([]);
  });

  it("(e) a blocked tile is not a drag source -> resolveDrop refuses defensively", () => {
    const blocked = card({
      id: "WF-BLOCKED",
      status: "blocked",
      stage: "implementation",
    });
    const lanes = groupIntoLanes([blocked]);
    const parkedLane = laneByKey(lanes, "parked");

    const plan = resolveDrop(blocked, parkedLane, 0, lanes);

    expect(plan.calls).toEqual([]);
  });

  it("parked cards STILL reorder WITHIN Parked via setOrder only (no move call)", () => {
    const p1 = card({ id: "WF-P1", status: "parked", order: 10 });
    const p2 = card({ id: "WF-P2", status: "parked", order: 20 });
    const p3 = card({ id: "WF-P3", status: "parked", order: 30 });
    const lanes = groupIntoLanes([p1, p2, p3]);

    // Backward drag P3 onto P1 within Parked -> destCards [P1,P2], index 0
    // -> before P1 = P1.order(10) - 10 = 0. A setOrder, never a move.
    const { lane, index } = locateDropTarget("WF-P1", lanes);
    const plan = resolveDrop(p3, lane!, index, lanes);

    expect(plan.calls).toEqual([{ kind: "setOrder", id: "WF-P3", order: 0 }]);
  });
});

describe("locateDropTarget", () => {
  it("resolves a drop onto a lane's own droppable id to the end of that lane", () => {
    const a = card({ id: "WF-A", status: "planned" });
    const lanes = groupIntoLanes([a]);

    const { lane, index } = locateDropTarget("parked", lanes);

    expect(lane?.key).toBe("parked");
    expect(index).toBe(0); // parked lane is empty
  });

  it("resolves a drop onto a card id to that card's lane + index", () => {
    const a = card({ id: "WF-A", status: "planned", order: 10 });
    const b = card({ id: "WF-B", status: "planned", order: 20 });
    const lanes = groupIntoLanes([a, b]);

    const { lane, index } = locateDropTarget("WF-B", lanes);

    expect(lane?.key).toBe("backlog");
    expect(index).toBe(1);
  });

  it("returns an undefined lane for an unknown id", () => {
    const lanes = groupIntoLanes([]);
    const { lane } = locateDropTarget("nonexistent", lanes);
    expect(lane).toBeUndefined();
  });
});
