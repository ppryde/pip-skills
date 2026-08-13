import { describe, expect, it } from "vitest";
import type { BoardCard } from "../api/types";
import {
  beastAnchorX,
  boundaryX,
  campfireX,
  computeSegments,
  frozenSegment,
  globalPxPerWeight,
  laneUsableWidth,
  openDependencies,
  orderChildrenForTrail,
  orderEpicsForDisplay,
  statusGroupOf,
  totalWeight,
  trailEndX,
  trimSegmentForMarkers,
  weightOf,
  BEAST_ANCHOR_OFFSET_PX,
  BEAST_ICON_SIZE_PX,
  BEAST_RESERVE_PX,
  CAMPFIRE_FRACTION,
  MIN_PX_PER_WEIGHT,
  TRAILHEAD_ICON_SIZE_PX,
  TRAILHEAD_PADDING_PX,
  TRAILHEAD_RESERVE_PX,
} from "./atlasTrailLayout";

function child(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    title: `Title ${overrides.id}`,
    status: "planned",
    stage: null,
    complexity: null,
    priority: null,
    sprint: null,
    parent: "WF-EPIC",
    depends_on: [],
    order: 0,
    budget: { estimate: null, actual: 0 },
    is_epic: false,
    ready: true,
    rollup: null,
    created: "2026-07-14",
    updated: "2026-08-06",
    checklist: [],
    labels: [],
    body: "",
    links: [],
    pr: null,
    ...overrides,
  };
}

describe("weightOf", () => {
  it("maps complexity S/M/L/XL onto the rarityStars 1-4 scale", () => {
    expect(weightOf(child({ id: "a", complexity: "S" }))).toBe(1);
    expect(weightOf(child({ id: "b", complexity: "M" }))).toBe(2);
    expect(weightOf(child({ id: "c", complexity: "L" }))).toBe(3);
    expect(weightOf(child({ id: "d", complexity: "XL" }))).toBe(4);
  });

  it("floors an unset/unrecognised complexity to weight 1, never 0 — a zero-weight child would collapse to a zero-length segment", () => {
    expect(weightOf(child({ id: "e", complexity: null }))).toBe(1);
    expect(weightOf(child({ id: "f", complexity: "XXL" }))).toBe(1);
  });
});

describe("statusGroupOf", () => {
  it("groups done and abandoned together as 'done' (abandoned shares done's priority)", () => {
    expect(statusGroupOf(child({ id: "a", status: "done" }))).toBe("done");
    expect(statusGroupOf(child({ id: "b", status: "abandoned" }))).toBe("done");
  });

  it("maps in-flight to 'in-progress'", () => {
    expect(statusGroupOf(child({ id: "a", status: "in-flight" }))).toBe("in-progress");
  });

  it("maps planned/blocked/parked to 'todo' — blocked is an overlay (open depends_on), not its own status group", () => {
    expect(statusGroupOf(child({ id: "a", status: "planned" }))).toBe("todo");
    expect(statusGroupOf(child({ id: "b", status: "blocked" }))).toBe("todo");
    expect(statusGroupOf(child({ id: "c", status: "parked" }))).toBe("todo");
  });
});

describe("orderChildrenForTrail", () => {
  it("orders done/abandoned before in-progress before todo", () => {
    const kids = [
      child({ id: "todo-1", status: "planned", order: 1 }),
      child({ id: "prog-1", status: "in-flight", order: 1 }),
      child({ id: "done-1", status: "done", order: 1 }),
    ];
    const ordered = orderChildrenForTrail(kids).map((c) => c.id);
    expect(ordered).toEqual(["done-1", "prog-1", "todo-1"]);
  });

  it("interleaves abandoned with done purely by board `order`", () => {
    const kids = [
      child({ id: "done-2", status: "done", order: 2 }),
      child({ id: "abandoned-1", status: "abandoned", order: 1 }),
      child({ id: "done-3", status: "done", order: 3 }),
    ];
    const ordered = orderChildrenForTrail(kids).map((c) => c.id);
    expect(ordered).toEqual(["abandoned-1", "done-2", "done-3"]);
  });

  it("sorts within each status group by board `order`", () => {
    const kids = [
      child({ id: "todo-b", status: "planned", order: 5 }),
      child({ id: "todo-a", status: "planned", order: 2 }),
    ];
    const ordered = orderChildrenForTrail(kids).map((c) => c.id);
    expect(ordered).toEqual(["todo-a", "todo-b"]);
  });

  it("does not mutate the input array", () => {
    const kids = [child({ id: "a", status: "planned", order: 2 }), child({ id: "b", status: "done", order: 1 })];
    const original = [...kids];
    orderChildrenForTrail(kids);
    expect(kids).toEqual(original);
  });
});

describe("laneUsableWidth", () => {
  it("subtracts the beast reserve and the trailhead reserve", () => {
    expect(laneUsableWidth(500)).toBe(500 - BEAST_RESERVE_PX - TRAILHEAD_RESERVE_PX);
  });

  it("floors at 40 for a very narrow lane", () => {
    expect(laneUsableWidth(50)).toBe(40);
  });
});

// Impl-review round 2 (user amendment): the trailhead village icon grew
// from ~20px to ~28-32px ("it is a town after all") — its reserve must be
// DERIVED from the icon's own size + padding, never a bare literal, same
// discipline as BEAST_RESERVE_PX (round 1, finding 1), so a future icon
// resize can never end up short of clearance again.
describe("TRAILHEAD_RESERVE_PX", () => {
  it("is derived from TRAILHEAD_ICON_SIZE_PX + TRAILHEAD_PADDING_PX, not a bare literal", () => {
    expect(TRAILHEAD_RESERVE_PX).toBe(TRAILHEAD_ICON_SIZE_PX + TRAILHEAD_PADDING_PX);
  });

  it("the icon is visibly grander than the ~20px trail markers — doubled to 60px (user amendment) from HANDOFF's original 28-32px tuning", () => {
    expect(TRAILHEAD_ICON_SIZE_PX).toBe(60);
    expect(TRAILHEAD_ICON_SIZE_PX).toBeGreaterThan(20);
  });
});

// Impl-review round 1, finding 1: HANDOFF's plain "64" beast reserve
// undersizes the beast's own footprint — BEAST_ANCHOR_OFFSET_PX(26) +
// BEAST_ICON_SIZE_PX(48, BeastFace's actual rendered size) = 74, so a 64px
// reserve clips 10px off the bottom of every Down-mode beast. The reserve
// must be DERIVED from those two constants, never a bare literal, so every
// caller's clamp/content-height math (AtlasTrail.tsx, AtlasTrailVertical.tsx)
// can never silently drift out of sync with the beast's real size again.
describe("BEAST_RESERVE_PX", () => {
  it("is derived from BEAST_ANCHOR_OFFSET_PX + BEAST_ICON_SIZE_PX, not a bare literal", () => {
    expect(BEAST_RESERVE_PX).toBe(BEAST_ANCHOR_OFFSET_PX + BEAST_ICON_SIZE_PX);
  });

  it("is large enough that a beast anchored at the reserve's own edge never overflows it", () => {
    // The heaviest epic's trail end sits at exactly `laneWidth - BEAST_RESERVE_PX`
    // (by construction of laneUsableWidth/globalPxPerWeight) — its beast
    // anchor is then trailEnd + BEAST_ANCHOR_OFFSET_PX, and the beast's own
    // footprint extends BEAST_ICON_SIZE_PX further. All of that must still
    // fit inside `laneWidth`.
    const laneWidth = 500;
    const trailEnd = laneWidth - BEAST_RESERVE_PX;
    const beastAnchor = beastAnchorX(trailEnd);
    expect(beastAnchor + BEAST_ICON_SIZE_PX).toBeLessThanOrEqual(laneWidth);
  });
});

describe("totalWeight", () => {
  it("sums weightOf across children", () => {
    const kids = [child({ id: "a", complexity: "S" }), child({ id: "b", complexity: "L" })];
    expect(totalWeight(kids)).toBe(1 + 3);
  });

  it("is 0 for an epic with no children", () => {
    expect(totalWeight([])).toBe(0);
  });
});

describe("globalPxPerWeight", () => {
  // usable=1000, heaviest=10 => natural ratio 100, comfortably above
  // MIN_PX_PER_WEIGHT(64) so these exercise the un-floored division path.
  it("divides usable width by the heaviest epic's total weight", () => {
    expect(globalPxPerWeight([4, 10, 2], 1000)).toBeCloseTo(100, 5);
  });

  it("floors the heaviest weight at 1 so an all-childless board never divides by zero", () => {
    expect(globalPxPerWeight([0, 0], 200)).toBeCloseTo(200, 5);
  });

  it("same weight means same on-screen length on every row — a downstream invariant", () => {
    const pxPerWeight = globalPxPerWeight([4, 10], 1000);
    expect(4 * pxPerWeight).toBeCloseTo(400, 5);
    // The heaviest epic (10) spans the full usable width.
    expect(10 * pxPerWeight).toBeCloseTo(1000, 5);
  });

  // MIN_PX_PER_WEIGHT(64) — a cramped board (small usable relative to the
  // heaviest epic's total weight) floors here instead of compressing
  // further: usable/heaviest = 200/50 = 4, well under the floor, so the
  // heaviest epic's trail deliberately overspills `usable` by design
  // (EpicAtlas.tsx's `trailWidth` then lets `.atlas-chart` scroll to it).
  it("floors at MIN_PX_PER_WEIGHT when the natural ratio undershoots it — cards keep breathing room and the trail overspills instead of compressing further", () => {
    expect(globalPxPerWeight([50], 200)).toBe(MIN_PX_PER_WEIGHT);
    // The floor wins over the (much smaller) natural division result.
    expect(MIN_PX_PER_WEIGHT).toBeGreaterThan(200 / 50);
  });
});

describe("computeSegments", () => {
  it("lays out cumulative-weight segments starting at the trailhead reserve", () => {
    const kids = [child({ id: "a", complexity: "S" }), child({ id: "b", complexity: "M" })];
    const segs = computeSegments(kids, 10);
    expect(segs[0].start).toBe(TRAILHEAD_RESERVE_PX);
    expect(segs[0].end).toBe(TRAILHEAD_RESERVE_PX + 10); // weight 1 * 10
    expect(segs[1].start).toBe(segs[0].end);
    expect(segs[1].end).toBe(TRAILHEAD_RESERVE_PX + 10 + 20); // + weight 2 * 10
  });
});

describe("trailEndX / beastAnchorX", () => {
  it("trailEndX = trailhead reserve + total weight * pxPerWeight", () => {
    expect(trailEndX(5, 10)).toBe(TRAILHEAD_RESERVE_PX + 50);
  });

  it("beastAnchorX adds the beast anchor offset", () => {
    expect(beastAnchorX(100)).toBe(100 + BEAST_ANCHOR_OFFSET_PX);
  });
});

describe("boundaryX", () => {
  it("stands at the trailhead reserve when nothing is done", () => {
    const kids = [child({ id: "a", status: "planned" }), child({ id: "b", status: "in-flight" })];
    const segs = computeSegments(orderChildrenForTrail(kids), 10);
    expect(boundaryX(segs)).toBe(TRAILHEAD_RESERVE_PX);
  });

  it("stands at the last done|abandoned segment's end, whichever came last in trail order", () => {
    const kids = [
      child({ id: "done-1", status: "done", complexity: "S", order: 1 }),
      child({ id: "abandoned-1", status: "abandoned", complexity: "M", order: 2 }),
      child({ id: "prog-1", status: "in-flight", complexity: "L", order: 1 }),
    ];
    const ordered = orderChildrenForTrail(kids);
    const segs = computeSegments(ordered, 10);
    // walked ground = done-1 (weight 1) + abandoned-1 (weight 2) = 30px
    expect(boundaryX(segs)).toBe(TRAILHEAD_RESERVE_PX + 30);
  });
});

describe("frozenSegment / campfireX", () => {
  it("finds the first in-progress segment as the frozen quest", () => {
    const kids = [child({ id: "done-1", status: "done" }), child({ id: "prog-1", status: "in-flight", complexity: "M" })];
    const ordered = orderChildrenForTrail(kids);
    const segs = computeSegments(ordered, 10);
    const frozen = frozenSegment(segs);
    expect(frozen?.child.id).toBe("prog-1");
  });

  it("places the campfire 78% into the frozen segment", () => {
    const kids = [child({ id: "prog-1", status: "in-flight", complexity: "M" })]; // weight 2 => 20px segment
    const segs = computeSegments(orderChildrenForTrail(kids), 10);
    const x = campfireX(segs);
    const frozen = frozenSegment(segs)!;
    expect(x).toBeCloseTo(frozen.start + (frozen.end - frozen.start) * CAMPFIRE_FRACTION, 5);
  });

  it("falls back to the done|next boundary when there is no in-progress child to freeze on", () => {
    const kids = [child({ id: "done-1", status: "done", complexity: "S" })];
    const segs = computeSegments(orderChildrenForTrail(kids), 10);
    expect(campfireX(segs)).toBe(boundaryX(segs));
  });
});

describe("trimSegmentForMarkers", () => {
  it("cuts a gap out of the middle of a segment", () => {
    const out = trimSegmentForMarkers(0, 100, [{ at: 50, radius: 10 }]);
    expect(out).toEqual([[0, 40], [60, 100]]);
  });

  it("cuts gaps at both ends (waypoint markers at each segment boundary)", () => {
    const out = trimSegmentForMarkers(0, 100, [
      { at: 0, radius: 15 },
      { at: 100, radius: 15 },
    ]);
    expect(out).toEqual([[15, 85]]);
  });

  it("drops a sub-interval narrower than 0.5px", () => {
    const out = trimSegmentForMarkers(0, 10, [{ at: 5, radius: 10 }]);
    expect(out).toEqual([]);
  });

  it("returns the whole segment unchanged when no cuts fall inside it", () => {
    const out = trimSegmentForMarkers(0, 100, [{ at: 500, radius: 10 }]);
    expect(out).toEqual([[0, 100]]);
  });
});

describe("openDependencies", () => {
  it("returns depends_on targets that are not yet done", () => {
    const cardsById = new Map<string, BoardCard>([
      ["WF-1", child({ id: "WF-1", status: "in-flight" })],
      ["WF-2", child({ id: "WF-2", status: "done" })],
    ]);
    const c = child({ id: "WF-3", depends_on: ["WF-1", "WF-2"] });
    expect(openDependencies(c, cardsById)).toEqual(["WF-1"]);
  });

  it("returns an empty array once every dependency is done", () => {
    const cardsById = new Map<string, BoardCard>([["WF-1", child({ id: "WF-1", status: "done" })]]);
    const c = child({ id: "WF-2", depends_on: ["WF-1"] });
    expect(openDependencies(c, cardsById)).toEqual([]);
  });

  it("treats a dangling dependency id (target not on the board) as open", () => {
    const c = child({ id: "WF-2", depends_on: ["WF-GONE"] });
    expect(openDependencies(c, new Map<string, BoardCard>())).toEqual(["WF-GONE"]);
  });
});

function epic(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return child({ parent: null, is_epic: true, ...overrides });
}

describe("orderEpicsForDisplay", () => {
  it("filters out done epics when hideVanquished is true", () => {
    const epics = [epic({ id: "a", status: "in-flight" }), epic({ id: "b", status: "done" })];
    expect(orderEpicsForDisplay(epics, true).map((e) => e.id)).toEqual(["a"]);
  });

  it("sorts done epics LAST when shown, preserving the relative order of everything else", () => {
    const epics = [
      epic({ id: "a", status: "done" }),
      epic({ id: "b", status: "in-flight" }),
      epic({ id: "c", status: "parked" }),
      epic({ id: "d", status: "done" }),
    ];
    expect(orderEpicsForDisplay(epics, false).map((e) => e.id)).toEqual(["b", "c", "a", "d"]);
  });

  it("does not mutate the input array", () => {
    const epics = [epic({ id: "a", status: "done" }), epic({ id: "b", status: "in-flight" })];
    const original = [...epics];
    orderEpicsForDisplay(epics, false);
    expect(epics).toEqual(original);
  });
});
