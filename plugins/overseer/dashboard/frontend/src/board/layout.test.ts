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
    created: "",
    updated: "",
    checklist: [],
    labels: [],
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

  it("sorts by updated recency descending (newest first), ignoring order", () => {
    const oldest = card({ id: "WF-OLDEST", order: 5, updated: "2026-07-01T09:00" });
    const newest = card({ id: "WF-NEWEST", order: 999, updated: "2026-07-20T09:00" });
    const middle = card({ id: "WF-MIDDLE", order: 10, updated: "2026-07-10T09:00" });

    const lanes = groupIntoLanes([oldest, newest, middle]);
    const backlog = laneByKey(lanes, "backlog");

    expect(backlog.cards.map((x) => x.id)).toEqual([
      "WF-NEWEST",
      "WF-MIDDLE",
      "WF-OLDEST",
    ]);
  });

  it("tiebreaks equal `updated` on `created` descending, then on `id` ascending", () => {
    const sameUpdatedNewerCreated = card({
      id: "WF-B",
      updated: "2026-07-10T09:00",
      created: "2026-07-05",
    });
    const sameUpdatedOlderCreated = card({
      id: "WF-A",
      updated: "2026-07-10T09:00",
      created: "2026-07-01",
    });
    const fullTie1 = card({
      id: "WF-Z",
      updated: "2026-07-10T09:00",
      created: "2026-07-05",
    });
    const fullTie2 = card({
      id: "WF-Y",
      updated: "2026-07-10T09:00",
      created: "2026-07-05",
    });

    const lanes = groupIntoLanes([
      sameUpdatedOlderCreated,
      sameUpdatedNewerCreated,
      fullTie1,
      fullTie2,
    ]);
    const backlog = laneByKey(lanes, "backlog");

    // WF-B (created 07-05) outranks WF-A (created 07-01) despite equal
    // `updated`; WF-B/WF-Z share both timestamps so `id` breaks the tie
    // (WF-B < WF-Y < WF-Z alphabetically), then WF-A trails last.
    expect(backlog.cards.map((x) => x.id)).toEqual(["WF-B", "WF-Y", "WF-Z", "WF-A"]);
  });

  it("treats blank/missing `updated`/`created` as epoch 0, sorting them last", () => {
    const timestamped = card({ id: "WF-FRESH", updated: "2026-07-01T09:00" });
    const blank = card({ id: "WF-BLANK", updated: "", created: "" });

    const lanes = groupIntoLanes([blank, timestamped]);
    const backlog = laneByKey(lanes, "backlog");

    expect(backlog.cards.map((x) => x.id)).toEqual(["WF-FRESH", "WF-BLANK"]);
  });

  it("keeps an epic and its same-lane children contiguous, children ordered by recency desc, group ranked by its most-recently-updated member", () => {
    const epic = card({
      id: "WF-EPIC",
      is_epic: true,
      status: "planned",
      updated: "2026-07-01T09:00", // epic itself is stale...
    });
    const staleChild = card({
      id: "WF-CHILD-OLD",
      parent: "WF-EPIC",
      status: "planned",
      updated: "2026-07-02T09:00",
    });
    const freshChild = card({
      id: "WF-CHILD-NEW",
      parent: "WF-EPIC",
      status: "planned",
      updated: "2026-07-15T09:00", // ...but this child was touched recently
    });
    // A lone top-level card, fresher than the epic itself but staler than
    // the epic's freshest child — should rank BETWEEN the group and nothing,
    // proving the group's rank comes from its freshest member, not the epic.
    const loneCard = card({
      id: "WF-LONE",
      status: "planned",
      updated: "2026-07-10T09:00",
    });

    const lanes = groupIntoLanes([epic, staleChild, freshChild, loneCard]);
    const backlog = laneByKey(lanes, "backlog");

    // The epic group (ranked by freshChild's 07-15) outranks WF-LONE
    // (07-10); within the group, epic renders first, then children by
    // recency desc (freshChild before staleChild).
    expect(backlog.cards.map((x) => x.id)).toEqual([
      "WF-EPIC",
      "WF-CHILD-NEW",
      "WF-CHILD-OLD",
      "WF-LONE",
    ]);
  });

  it("orders a child whose epic lives in a DIFFERENT lane by the child's own recency (no grouping across lanes)", () => {
    const epic = card({
      id: "WF-EPIC",
      is_epic: true,
      status: "in-flight",
      stage: "implementation",
      updated: "2026-07-20T09:00",
    });
    // This child is DONE (different lane from its in-flight epic) — it must
    // stand alone in Done, ordered by its own recency, never hidden/grouped
    // away from its lane's normal cards.
    const doneChild = card({
      id: "WF-CHILD",
      parent: "WF-EPIC",
      status: "done",
      updated: "2026-07-25T09:00",
    });
    const otherDoneCard = card({
      id: "WF-OTHER-DONE",
      status: "done",
      updated: "2026-07-05T09:00",
    });

    const lanes = groupIntoLanes([epic, doneChild, otherDoneCard]);
    const done = laneByKey(lanes, "done");

    // doneChild (07-25) outranks otherDoneCard (07-05) purely on its own
    // recency — the epic's own timestamp/lane never enters into it.
    expect(done.cards.map((x) => x.id)).toEqual(["WF-CHILD", "WF-OTHER-DONE"]);
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
