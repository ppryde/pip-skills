import { describe, expect, it } from "vitest";
import { groupIntoLanes, STAGES } from "./layout";
import type { BoardCard } from "../api/types";

/** Minimal card builder — fills every required field with a sane default. */
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
    ...overrides,
  };
}

function laneByKey(lanes: ReturnType<typeof groupIntoLanes>, key: string) {
  const lane = lanes.find((l) => l.key === key);
  if (!lane) throw new Error(`lane ${key} not found`);
  return lane;
}

describe("groupIntoLanes", () => {
  it("places an epic's children in their OWN lanes (never hidden/nested/duplicated) even when they span >=3 lanes, and the epic by its own status", () => {
    const epic = card({ id: "WF-EPIC", is_epic: true, status: "planned", order: 10 });
    const doneChild = card({ id: "WF-C1", parent: "WF-EPIC", status: "done", order: 10 });
    const inFlightChild = card({
      id: "WF-C2",
      parent: "WF-EPIC",
      status: "in-flight",
      stage: "implementation",
      order: 10,
    });
    const plannedChild = card({ id: "WF-C3", parent: "WF-EPIC", status: "planned", order: 20 });

    const lanes = groupIntoLanes([epic, doneChild, inFlightChild, plannedChild]);

    // Every card appears exactly once across the whole board.
    const allCards = lanes.flatMap((l) => l.cards);
    expect(allCards).toHaveLength(4);
    const ids = allCards.map((c) => c.id);
    expect(new Set(ids).size).toBe(4); // no duplicates

    // The epic is placed by its OWN status (planned -> backlog), not bundled with children.
    const backlog = laneByKey(lanes, "backlog");
    expect(backlog.cards.map((c) => c.id)).toContain("WF-EPIC");
    expect(backlog.cards.map((c) => c.id)).toContain("WF-C3");

    // Done child lands in Done, untouched by epic membership.
    const done = laneByKey(lanes, "done");
    expect(done.cards.map((c) => c.id)).toEqual(["WF-C1"]);

    // In-flight child lands in its stage lane.
    const implementation = laneByKey(lanes, "stage:implementation");
    expect(implementation.cards.map((c) => c.id)).toEqual(["WF-C2"]);

    // No lane silently swallows a child under the epic.
    for (const lane of lanes) {
      for (const c of lane.cards) {
        if (c.parent === "WF-EPIC") {
          expect(["WF-C1", "WF-C2", "WF-C3"]).toContain(c.id);
        }
      }
    }
  });

  it("sorts by order ascending, tiebreaking on id ascending", () => {
    const a = card({ id: "WF-B", order: 10 });
    const b = card({ id: "WF-A", order: 10 }); // same order as `a`, id sorts first
    const c = card({ id: "WF-C", order: 5 });

    const lanes = groupIntoLanes([a, b, c]);
    const backlog = laneByKey(lanes, "backlog");

    expect(backlog.cards.map((x) => x.id)).toEqual(["WF-C", "WF-A", "WF-B"]);
  });

  it("populates every lane bucket, including archive, with one card each", () => {
    const cards: BoardCard[] = [
      card({ id: "WF-BACKLOG", status: "planned" }),
      ...STAGES.map((stage, i) =>
        card({ id: `WF-STAGE-${i}`, status: "in-flight", stage })
      ),
      card({ id: "WF-PARKED", status: "parked" }),
      card({ id: "WF-DONE", status: "done" }),
      card({ id: "WF-ARCHIVE", status: "abandoned" }),
    ];

    const lanes = groupIntoLanes(cards);

    expect(laneByKey(lanes, "backlog").cards.map((c) => c.id)).toEqual(["WF-BACKLOG"]);
    STAGES.forEach((stage, i) => {
      expect(laneByKey(lanes, `stage:${stage}`).cards.map((c) => c.id)).toEqual([
        `WF-STAGE-${i}`,
      ]);
    });
    expect(laneByKey(lanes, "parked").cards.map((c) => c.id)).toEqual(["WF-PARKED"]);
    expect(laneByKey(lanes, "done").cards.map((c) => c.id)).toEqual(["WF-DONE"]);
    expect(laneByKey(lanes, "archive").cards.map((c) => c.id)).toEqual(["WF-ARCHIVE"]);

    // All seven stage lanes are always present, in STAGE order, even when empty elsewhere.
    const stageLaneKeys = lanes.filter((l) => l.kind === "stage").map((l) => l.key);
    expect(stageLaneKeys).toEqual(STAGES.map((s) => `stage:${s}`));
  });

  it("lands a blocked card with stage==null in Backlog", () => {
    const blocked = card({ id: "WF-BLOCKED", status: "blocked", stage: null });
    const lanes = groupIntoLanes([blocked]);

    expect(laneByKey(lanes, "backlog").cards.map((c) => c.id)).toEqual(["WF-BLOCKED"]);
    for (const stage of STAGES) {
      expect(laneByKey(lanes, `stage:${stage}`).cards).toHaveLength(0);
    }
  });

  it("lands a blocked card WITH a stage in that stage lane", () => {
    const blocked = card({ id: "WF-BLOCKED", status: "blocked", stage: "impl-review" });
    const lanes = groupIntoLanes([blocked]);

    expect(laneByKey(lanes, "stage:impl-review").cards.map((c) => c.id)).toEqual([
      "WF-BLOCKED",
    ]);
    expect(laneByKey(lanes, "backlog").cards).toHaveLength(0);
  });

  it("always returns all seven stage lanes even when every card list is empty", () => {
    const lanes = groupIntoLanes([]);
    const stageLaneKeys = lanes.filter((l) => l.kind === "stage").map((l) => l.key);
    expect(stageLaneKeys).toEqual(STAGES.map((s) => `stage:${s}`));
    expect(lanes.every((l) => l.cards.length === 0)).toBe(true);
  });
});
