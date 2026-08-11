import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import type { BoardCard, Rollup } from "../api/types";
import { seedFor } from "../board/atlasGeometry";
import {
  TRAILHEAD_ICON_SIZE_PX,
  TRAILHEAD_RESERVE_PX,
  beastAnchorX,
  computeSegments,
  orderChildrenForTrail,
  totalWeight,
  trailEndX,
} from "../board/atlasTrailLayout";
import { beastFor } from "../board/beastName";
import { ARC_PX_PER_UNIT_SERPENTINE, serpentineTrail } from "../board/serpentineTrail";
import AtlasTrailVertical from "./AtlasTrailVertical";

function card(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    title: `Title ${overrides.id}`,
    status: "in-flight",
    stage: "implementation",
    complexity: null,
    priority: null,
    sprint: null,
    parent: null,
    depends_on: [],
    order: 10,
    budget: { estimate: null, actual: 0 },
    is_epic: true,
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

function child(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return card({ parent: "WF-EPIC", is_epic: false, ...overrides });
}

function rollup(overrides: Partial<Rollup> = {}): Rollup {
  return { done: 1, total: 3, estimate: 100000, actual: 42000, ...overrides };
}

function renderColumn(epic: BoardCard, childCards: BoardCard[], showNames = true) {
  const cardsById = new Map<string, BoardCard>([epic, ...childCards].map((c) => [c.id, c]));
  return render(
    <AtlasTrailVertical
      card={epic}
      rollup={rollup()}
      childCards={childCards}
      cardsById={cardsById}
      showNames={showNames}
    />
  );
}

describe("<AtlasTrailVertical/> (mobile Down orientation)", () => {
  it("marches top to bottom: the trailhead sits above the beast", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [child({ id: "k1", status: "done", complexity: "M" })];
    const { container } = renderColumn(epic, kids);

    const trailheadY = Number(
      container.querySelector(".atlas-trail__trailhead")!.getAttribute("transform")!.match(/,\s*([\d.-]+)\)/)![1]
    );
    const beastTransform = container.querySelector(".atlas-trail__beast")!.getAttribute("transform")!;
    const beastY = Number(beastTransform.split(",")[1].trim().replace(")", ""));
    expect(beastY).toBeGreaterThan(trailheadY);
  });

  // Impl-review round 2 (user amendment): "the walled-village trailhead
  // icon is too teeny — it is a town after all" — renders visibly grander
  // than the ~20px trail markers now, in Down mode too.
  it("renders the trailhead icon at TRAILHEAD_ICON_SIZE_PX, visibly larger than the ~20px trail markers", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [child({ id: "k1", status: "done", complexity: "M" })];
    const { container } = renderColumn(epic, kids);
    const icon = container.querySelector(".atlas-trail__trailhead image")!;
    expect(Number(icon.getAttribute("width"))).toBe(TRAILHEAD_ICON_SIZE_PX);
    expect(Number(icon.getAttribute("height"))).toBe(TRAILHEAD_ICON_SIZE_PX);
    expect(TRAILHEAD_ICON_SIZE_PX).toBeGreaterThan(20);
  });

  it("done epic: renders a slain beast", () => {
    const epic = card({ id: "WF-027", status: "done" });
    const kids = [child({ id: "k1", status: "done", complexity: "S" })];
    const { container } = renderColumn(epic, kids);
    expect(container.querySelector(".atlas-trail__beast--slain")).toBeInTheDocument();
    const beast = beastFor("WF-027");
    expect(Array.from(container.querySelectorAll("title")).map((t) => t.textContent)).toContain(
      `${beast.name} — vanquished!`
    );
  });

  it("in-flight epic: renders the party token at the done|next boundary", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [
      child({ id: "k1", status: "done", complexity: "S" }),
      child({ id: "k2", status: "in-flight", complexity: "M" }),
    ];
    const { container } = renderColumn(epic, kids);
    expect(container.querySelector(".atlas-trail__party")).toBeInTheDocument();
  });

  it("heavier children yield a taller column than lighter ones on the same flat per-complexity scale", () => {
    const heavyEpic = card({ id: "WF-HEAVY", status: "in-flight" });
    const heavyKid = child({ id: "h1", status: "done", complexity: "XL" });
    const lightEpic = card({ id: "WF-LIGHT", status: "in-flight" });
    const lightKid = child({ id: "l1", status: "done", complexity: "S" });

    const heavy = renderColumn(heavyEpic, [heavyKid]);
    const light = renderColumn(lightEpic, [lightKid]);

    const heavySvg = heavy.container.querySelector("svg")!;
    const lightSvg = light.container.querySelector("svg")!;
    const heavyHeight = Number(heavySvg.getAttribute("viewBox")!.split(" ")[3]);
    const lightHeight = Number(lightSvg.getAttribute("viewBox")!.split(" ")[3]);
    expect(heavyHeight).toBeGreaterThan(lightHeight);
  });

  it("todo child renders a name-tag only when showNames is true", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    // "Faraway Quest" needs a TRAILING todo sibling so it isn't the trail's
    // last child — otherwise its own tag would be suppressed by the
    // last-child beast-clearance rule and this test wouldn't be exercising
    // the showNames toggle it's named for. (A preceding sibling wouldn't
    // help: todos already sort after done/in-progress, so a todo with
    // nothing after it stays last regardless of what precedes it.)
    const todo = child({ id: "k1", title: "Faraway Quest", status: "planned", complexity: "S", order: 1 });
    const later = child({ id: "k2", title: "Later Quest", status: "planned", complexity: "S", order: 2 });

    const shown = renderColumn(epic, [todo, later], true);
    const shownTags = Array.from(shown.container.querySelectorAll(".trail-tag--todo"));
    expect(shownTags.map((t) => t.textContent)).toContain("Faraway Quest");

    const hidden = renderColumn(epic, [todo, later], false);
    expect(hidden.container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
  });

  it("last todo child's name-tag is suppressed (marker sits beast-adjacent) — earlier todo tags still render", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const earlier = child({ id: "k0", title: "Earlier Quest", status: "planned", complexity: "S", order: 1 });
    const last = child({ id: "k1", title: "Faraway Quest", status: "planned", complexity: "S", order: 2 });

    const { container } = renderColumn(epic, [earlier, last], true);
    const tags = Array.from(container.querySelectorAll(".trail-tag--todo")).map((t) => t.textContent);
    expect(tags).toContain("Earlier Quest");
    expect(tags).not.toContain("Faraway Quest");
  });

  it("in-flight epic: when the in-progress child IS the last child, the AT-HAND pennant label is suppressed", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const prog = child({ id: "k1", status: "in-flight", complexity: "M" });
    const { container } = renderColumn(epic, [prog]);
    expect(container.querySelector(".atlas-trail__pennant--athand")).not.toBeInTheDocument();
  });

  it("in-flight epic: when a todo trails the in-progress child (not last), the AT-HAND pennant label renders", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const prog = child({ id: "k1", status: "in-flight", complexity: "M", order: 1 });
    const todoAfter = child({ id: "k2", status: "planned", complexity: "S", order: 2 });
    const { container } = renderColumn(epic, [prog, todoAfter]);
    expect(container.querySelector(".atlas-trail__pennant--athand")).toHaveTextContent("◆ AT HAND");
  });

  it("re-measures its own column WIDTH on ResizeObserver callback (each column self-measures — no shared scale in down-mode)", () => {
    let capturedCallback: ResizeObserverCallback | null = null;
    class MockResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        capturedCallback = cb;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);

    const epic = card({ id: "WF-085", status: "in-flight" });
    const { container } = renderColumn(epic, []);

    expect(capturedCallback).not.toBeNull();
    act(() => {
      capturedCallback!(
        [{ contentRect: { width: 280, height: 0 } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")!.split(" ")[2]).toBe("280");
  });

  // Impl-review round 1, finding 5's explicit test ask: "marker positions
  // on the curve" — a rendered marker's (cx, cy) must land EXACTLY where
  // the serpentine geometry module itself says that Y should be, not on
  // some flat/straight x.
  it("a waypoint marker's (cx, cy) matches serpentineTrail's own pointAt for that child's cumulative-weight position", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    // Two children so the second one's marker lands past band 0's turn —
    // a genuinely swept (non-trivial) x, not just the trailhead's own x.
    const kids = [
      child({ id: "k1", status: "done", complexity: "L", order: 1 }), // weight 3
      child({ id: "k2", status: "done", complexity: "L", order: 2 }), // weight 3
    ];
    const { container } = renderColumn(epic, kids);

    // Reproduce the component's own geometry independently, off the same
    // pure modules, at the DEFAULT_COLUMN_WIDTH it renders at pre-measurement.
    const ordered = orderChildrenForTrail(kids);
    const segments = computeSegments(ordered, ARC_PX_PER_UNIT_SERPENTINE);
    const trail = serpentineTrail(280, seedFor("WF-085"));
    const expected = segments.map((s) => trail.pointAt(s.end));

    const markers = Array.from(container.querySelectorAll(".atlas-trail__waypoint--done circle"));
    expect(markers.length).toBe(2);
    markers.forEach((el, i) => {
      expect(Number(el.getAttribute("cx"))).toBeCloseTo(expected[i].x, 3);
      expect(Number(el.getAttribute("cy"))).toBeCloseTo(expected[i].y, 3);
    });
  });

  // Impl-review round 1, finding 5 / round 2, finding 2: "vertical advance
  // per complexity point reduced to roughly half the old flat scale" — a
  // component-level sanity check that the rendered content height
  // actually reflects the NEW arc-length-based scale, not the superseded
  // flat 72px/unit straight drop. Since positioning went genuinely
  // arc-length-based (round 2), the rendered height is no longer the raw
  // scalar directly — it's reproduced here via the same
  // serpentineTrail+atlasTrailLayout pipeline the component itself uses,
  // not a flat formula.
  it("renders at the new arc-length-based scale, not the superseded flat 72 straight drop", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [child({ id: "k1", status: "done", complexity: "XL" })]; // weight 4
    const { container } = renderColumn(epic, kids);

    const svg = container.querySelector("svg")!;
    const height = Number(svg.getAttribute("viewBox")!.split(" ")[3]);
    const totalWeightUnits = totalWeight(kids);

    const trail = serpentineTrail(280, seedFor("WF-085"));
    const newTrailEnd = trailEndX(totalWeightUnits, ARC_PX_PER_UNIT_SERPENTINE);
    const beastArc = beastAnchorX(newTrailEnd);
    const expectedHeight = trail.pointAt(beastArc).y + 48; // + BEAST_ICON_SIZE_PX
    expect(height).toBeCloseTo(expectedHeight, 1);

    // Well short of what the superseded flat 72px/unit scale (a straight
    // Y computation, no curve) would have needed for the same weight.
    const oldFlatHeight = TRAILHEAD_RESERVE_PX + totalWeightUnits * 72 + 26 + 48; // ANCHOR_OFFSET + ICON_SIZE
    expect(height).toBeLessThan(oldFlatHeight);
  });

  // Impl-review round 1, finding 1's explicit test ask: "assert Down-mode
  // beast bottom <= viewBox height" — the beast's own footprint
  // (BEAST_ICON_SIZE_PX) must fit inside the content height the reserve
  // was sized for, never clipped by the SVG's own viewBox.
  it("the beast's own footprint never overflows the SVG's viewBox height", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [child({ id: "k1", status: "done", complexity: "XL" })];
    const { container } = renderColumn(epic, kids);

    const svg = container.querySelector("svg")!;
    const viewBoxHeight = Number(svg.getAttribute("viewBox")!.split(" ")[3]);
    const beastTransform = container.querySelector(".atlas-trail__beast")!.getAttribute("transform")!;
    const beastY = Number(beastTransform.split(",")[1].trim().replace(")", ""));

    expect(beastY + 48).toBeLessThanOrEqual(viewBoxHeight); // 48 = BeastFace's rendered footprint
  });

  // Impl-review round 1, finding 3 (Down-mode half): a parked epic with
  // zero done and zero in-progress children — campfireX falls all the way
  // back to boundaryX — still cuts a gap in the line at that position.
  // (Round 2 note: the rendered path's Y is no longer the raw arc-length
  // scalar directly — arc-length parameterization means Y <= arc length
  // almost everywhere — so this compares against the UNCUT trailhead
  // POINT itself, via serpentineTrail, rather than a raw-pixel offset.)
  it("parked, all-todo epic (no done/in-progress children): the campfire still cuts a gap in the line", () => {
    const epic = card({ id: "WF-076", status: "parked" });
    const todo = child({ id: "k1", status: "planned", complexity: "M" });
    const { container } = renderColumn(epic, [todo]);

    expect(container.querySelector(".atlas-trail__campfire")).toBeInTheDocument();

    const trail = serpentineTrail(280, seedFor("WF-076"));
    const uncutStart = trail.pointAt(TRAILHEAD_RESERVE_PX);
    const firstPathD = container.querySelector(".atlas-trail__path")!.getAttribute("d")!;
    const match = firstPathD.match(/^M([\d.]+)\s([\d.]+)/)!;
    const firstPathStart = { x: Number(match[1]), y: Number(match[2]) };

    // A real cut moves the rendered path's start measurably away from the
    // raw, uncut trailhead point.
    const dist = Math.hypot(firstPathStart.x - uncutStart.x, firstPathStart.y - uncutStart.y);
    expect(dist).toBeGreaterThan(4);
  });

  // Impl-review round 2, finding 1 (both reviewers, independently): the
  // side-flip used to be INVERTED — a marker near the left wall (more room
  // to its right) got its tag anchored via CSS `right:`, which grows the
  // box LEFTWARD, landing the tag on the CROWDED side instead. This
  // asserts actual POSITION relative to the marker's own x (not just which
  // style key is present) for markers near BOTH walls.
  it("places the tag/pennant on the ROOMY side of the marker, not the crowded one — checked for markers near both walls", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [
      // Weight 1 (S) then weight 2 (M) — cumulative arc length
      // (TRAILHEAD_RESERVE_PX + 1/3 * ARC_PX_PER_UNIT_SERPENTINE, computed
      // below) lands one marker near the RIGHT wall and the other near
      // the LEFT wall — confirmed against the pure module below, not
      // asserted blind.
      child({ id: "k1", title: "Near right wall", status: "planned", complexity: "S", order: 1 }),
      child({ id: "k2", title: "Near left wall", status: "planned", complexity: "M", order: 2 }),
      // A trailing 3rd child keeps k2 from being the trail's LAST child, so
      // its own tag isn't caught by the last-child beast-clearance
      // suppression — that rule now falls on k3 instead, which stays out of
      // the ".trail-tag--todo" count below (tags.length is still 2: k1 + k2).
      child({ id: "k3", title: "Last Quest", status: "planned", complexity: "S", order: 3 }),
    ];
    const { container } = renderColumn(epic, kids);

    const trail = serpentineTrail(280, seedFor("WF-085")); // 280 = DEFAULT_COLUMN_WIDTH, pre-measurement
    const y1 = TRAILHEAD_RESERVE_PX + 1 * ARC_PX_PER_UNIT_SERPENTINE;
    const y2 = TRAILHEAD_RESERVE_PX + 3 * ARC_PX_PER_UNIT_SERPENTINE;
    const mx1 = trail.pointAt(y1).x;
    const mx2 = trail.pointAt(y2).x;
    // Sanity-check the fixture actually exercises both walls, rather than
    // asserting on a hand-computed number that could itself be wrong.
    expect(mx1).toBeGreaterThan(140); // right half of a 280px column
    expect(mx2).toBeLessThan(140); // left half

    const tags = Array.from(container.querySelectorAll(".trail-tag--todo"));
    expect(tags.length).toBe(2);
    const [tag1, tag2] = tags as HTMLElement[];

    // Marker 1 is near the right wall — the tag must sit to its LEFT
    // (anchored via `right:`, whose implied left edge is < mx1), never
    // anchored via `left:` (which would grow it further right, off the
    // column or back over the marker itself with no room).
    expect(tag1.style.right).not.toBe("");
    expect(tag1.style.left).toBe("");
    const tag1ImpliedLeftEdge = 280 - parseFloat(tag1.style.right);
    expect(tag1ImpliedLeftEdge).toBeLessThan(mx1);

    // Marker 2 is near the left wall — the tag must sit to its RIGHT
    // (anchored via `left:`, whose value is > mx2).
    expect(tag2.style.left).not.toBe("");
    expect(tag2.style.right).toBe("");
    expect(parseFloat(tag2.style.left)).toBeGreaterThan(mx2);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });
});
