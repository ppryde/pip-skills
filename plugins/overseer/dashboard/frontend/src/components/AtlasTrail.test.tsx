import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import type { BoardCard, Rollup } from "../api/types";
import { BEAST_RESERVE_PX, TRAILHEAD_ICON_SIZE_PX, TRAILHEAD_RESERVE_PX } from "../board/atlasTrailLayout";
import { beastFor } from "../board/beastName";
import { formatTokens } from "../board/formatTokens";
import AtlasTrail from "./AtlasTrail";

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
  return { done: 2, total: 5, estimate: 100000, actual: 42000, ...overrides };
}

function tooltipTexts(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("title")).map((t) => t.textContent ?? "");
}

// A stable, generous width so segment/marker math never collapses to the
// MIN_USABLE_PX floor mid-test.
const PX_PER_WEIGHT = 20;

function renderTrail(
  epic: BoardCard,
  childCards: BoardCard[],
  overrides: Partial<{
    rollup: Rollup;
    showNames: boolean;
    trailWidth: number;
    pxPerWeight: number;
    onOpenCard: (id: string) => void;
  }> = {}
) {
  const cardsById = new Map<string, BoardCard>([epic, ...childCards].map((c) => [c.id, c]));
  return render(
    <AtlasTrail
      card={epic}
      rollup={overrides.rollup ?? rollup()}
      childCards={childCards}
      cardsById={cardsById}
      pxPerWeight={overrides.pxPerWeight ?? PX_PER_WEIGHT}
      trailWidth={overrides.trailWidth ?? 600}
      showNames={overrides.showNames ?? true}
      onOpenCard={overrides.onOpenCard ?? vi.fn()}
    />
  );
}

describe("<AtlasTrail/>", () => {
  it("renders the trailhead icon and the beast at the epic's true (weight-scaled) end", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [child({ id: "k1", status: "done", complexity: "S" })];
    const { container } = renderTrail(epic, kids);
    expect(container.querySelector(".atlas-trail__trailhead")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__beast--alive")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__beast--slain")).not.toBeInTheDocument();
  });

  // Impl-review round 2 (user amendment): "the walled-village trailhead
  // icon is too teeny — it is a town after all" — renders visibly grander
  // than the ~20px trail markers now.
  it("renders the trailhead icon at TRAILHEAD_ICON_SIZE_PX, visibly larger than the ~20px trail markers", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [child({ id: "k1", status: "done", complexity: "S" })];
    const { container } = renderTrail(epic, kids);
    const icon = container.querySelector(".atlas-trail__trailhead image")!;
    expect(Number(icon.getAttribute("width"))).toBe(TRAILHEAD_ICON_SIZE_PX);
    expect(Number(icon.getAttribute("height"))).toBe(TRAILHEAD_ICON_SIZE_PX);
    expect(TRAILHEAD_ICON_SIZE_PX).toBeGreaterThan(20);
  });

  it("done epic: renders a slain beast and gold text", () => {
    const epic = card({ id: "WF-027", status: "done" });
    const kids = [child({ id: "k1", status: "done", complexity: "L" })];
    const { container } = renderTrail(epic, kids, { rollup: rollup({ done: 1, total: 1, actual: 210000 }) });
    expect(container.querySelector(".atlas-trail__beast--slain")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__gold")).toHaveTextContent(`+${formatTokens(210000)} gold`);
    const beast = beastFor("WF-027");
    expect(tooltipTexts(container)).toContain(`${beast.name} — vanquished!`);
  });

  it("renders a ✓ waypoint per done child with a 'quest cleared' tooltip, and does not render one for a todo child", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const doneChild = child({ id: "k1", title: "Cleared Quest", status: "done", updated: "2026-07-16", complexity: "S" });
    const todoChild = child({ id: "k2", status: "planned", complexity: "S" });
    const { container } = renderTrail(epic, [doneChild, todoChild]);
    expect(container.querySelectorAll(".atlas-trail__waypoint--done").length).toBe(1);
    expect(tooltipTexts(container)).toContain("Cleared Quest — cleared · 16 JUL");
  });

  it("renders a skull/grave marker for an abandoned child with a 'fell on the march' tooltip", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const abandonedChild = child({
      id: "k1",
      title: "Fallen Quest",
      status: "abandoned",
      updated: "2026-07-20",
      complexity: "M",
    });
    const { container } = renderTrail(epic, [abandonedChild]);
    expect(container.querySelector(".atlas-trail__waypoint--abandoned")).toBeInTheDocument();
    expect(tooltipTexts(container)).toContain("Fallen Quest — fell on the march · 20 JUL");
  });

  it("in-flight epic: the in-progress child gets the pulsing AT-HAND ring and pennant", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    // The in-progress child needs a TRAILING todo sibling so it is NOT the
    // trail's last child — done sorts before in-progress in trail order, so
    // a preceding done sibling alone still leaves in-progress last; only a
    // todo AFTER it moves it off the last-child slot. Otherwise its own
    // AT-HAND pennant label would be suppressed by the last-child
    // beast-clearance rule below, and this test would no longer be
    // exercising the pennant it's named for.
    const prog = child({ id: "k1", status: "in-flight", complexity: "M", order: 1 });
    const todoAfter = child({ id: "k2", status: "planned", complexity: "S", order: 2 });
    const { container } = renderTrail(epic, [prog, todoAfter]);
    expect(container.querySelector(".at-hand-ring")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__pennant--athand")).toHaveTextContent("◆ AT HAND");
    expect(tooltipTexts(container).some((t) => t.includes("the quest at hand"))).toBe(true);
  });

  it("in-flight epic: when the in-progress child IS the last child (no todos after it), the AT-HAND pennant label is suppressed — marker and tooltip still render", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const prog = child({ id: "k1", status: "in-flight", complexity: "M" });
    const { container } = renderTrail(epic, [prog]);
    expect(container.querySelector(".at-hand-ring")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__pennant--athand")).not.toBeInTheDocument();
    expect(tooltipTexts(container).some((t) => t.includes("the quest at hand"))).toBe(true);
  });

  it("parked epic: the in-progress child renders a plain diamond — NO ring, NO pennant — and a 'frozen mid-quest' tooltip", () => {
    const epic = card({ id: "WF-076", status: "parked" });
    const prog = child({ id: "k1", status: "in-flight", complexity: "M" });
    const { container } = renderTrail(epic, [prog]);
    expect(container.querySelector(".at-hand-ring")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__pennant--athand")).not.toBeInTheDocument();
    expect(tooltipTexts(container).some((t) => t.includes("frozen mid-quest"))).toBe(true);
  });

  it("parked epic: renders a campfire marker at 78% of the frozen segment, with a camped label, and no party token", () => {
    const epic = card({ id: "WF-076", status: "parked" });
    const prog = child({ id: "k1", status: "in-flight", complexity: "M" });
    const { container } = renderTrail(epic, [prog]);
    expect(container.querySelector(".atlas-trail__campfire")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__camped-label")).toHaveTextContent("camped — on hold");
    expect(container.querySelector(".atlas-trail__party")).not.toBeInTheDocument();
  });

  it("in-flight epic: renders the party token at the done|next boundary", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const done = child({ id: "k1", status: "done", complexity: "S" });
    const prog = child({ id: "k2", status: "in-flight", complexity: "M" });
    const { container } = renderTrail(epic, [done, prog]);
    expect(container.querySelector(".atlas-trail__party")).toBeInTheDocument();
    expect(tooltipTexts(container)).toContain("the party — 2/5 quests cleared");
  });

  it("todo child: renders a faded hollow waypoint regardless of its name-tag's own visibility", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    // A SOLE todo child is, by construction, also the trail's LAST child —
    // see the round 2 finding 5 tests below for why that means its own
    // name-tag is suppressed (clearance from the beast); the WAYPOINT
    // marker itself is unaffected by that and always renders.
    const todo = child({ id: "k1", title: "Faraway Quest", status: "planned", complexity: "S" });

    const shown = renderTrail(epic, [todo], { showNames: true });
    expect(shown.container.querySelector(".atlas-trail__waypoint--todo")).toBeInTheDocument();

    const hidden = renderTrail(epic, [todo], { showNames: false });
    expect(hidden.container.querySelector(".atlas-trail__waypoint--todo")).toBeInTheDocument();
    expect(hidden.container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
  });

  it("a NON-last todo child's name-tag shows normally when showNames is true", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [
      child({ id: "k1", title: "Faraway Quest", status: "planned", complexity: "S", order: 1 }),
      child({ id: "k2", title: "Last One", status: "planned", complexity: "S", order: 2 }), // last -> suppressed, see finding 5
    ];
    const shown = renderTrail(epic, kids, { showNames: true });
    expect(shown.container.querySelector(".trail-tag--todo")).toHaveTextContent("Faraway Quest");

    const hidden = renderTrail(epic, kids, { showNames: false });
    expect(hidden.container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
  });

  it("todo child name-tags alternate above and below the path so adjacent tags never collide", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    // Three children so the alternation check lands on the first TWO
    // (non-last) tags — the third (last) child's own tag is suppressed
    // (round 2, finding 5's beast-clearance rule) regardless of alternation.
    const kids = [
      child({ id: "k1", title: "First", status: "planned", complexity: "S", order: 1 }),
      child({ id: "k2", title: "Second", status: "planned", complexity: "S", order: 2 }),
      child({ id: "k3", title: "Third", status: "planned", complexity: "S", order: 3 }),
    ];
    const { container } = renderTrail(epic, kids, { showNames: true });
    const tags = Array.from(container.querySelectorAll(".trail-tag--todo"));
    expect(tags.length).toBe(2);
    // The first (non-suppressed) tag sits above the path, the second below.
    expect(tags[0]).not.toHaveClass("trail-tag--below");
    expect(tags[1]).toHaveClass("trail-tag--below");
    // Above and below anchor from opposite edges of their own box.
    expect((tags[0] as HTMLElement).style.transform).toContain("-100%");
    expect((tags[1] as HTMLElement).style.transform).not.toContain("-100%");
  });

  // Task 2: the above/below alternation is keyed off ONE running counter
  // shared across the done AND todo groups (Feature 3's greyed done tags
  // included), not two independent per-group counters — otherwise the
  // zig-zag would reset (or collide) wherever a done stretch hands off to a
  // todo one.
  it("the above/below alternation uses one shared counter across the done AND todo groups, in trail order", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [
      child({ id: "k1", title: "Cleared First", status: "done", complexity: "S", order: 1 }),
      child({ id: "k2", title: "Todo Second", status: "planned", complexity: "S", order: 2 }),
      child({ id: "k3", title: "Todo Third", status: "planned", complexity: "S", order: 3 }),
    ];
    const { container } = renderTrail(epic, kids, { showNames: true });
    // Trail order is done -> todo -> todo (orderChildrenForTrail); k3 is the
    // last child, so only k1 and k2's tags render.
    const tags = Array.from(container.querySelectorAll(".trail-tag"));
    expect(tags.length).toBe(2);
    expect(tags[0]).toHaveClass("trail-tag--done");
    expect(tags[0]).not.toHaveClass("trail-tag--below");
    expect(tags[1]).toHaveClass("trail-tag--todo");
    expect(tags[1]).toHaveClass("trail-tag--below");
  });

  it("blocked child (open depends_on): renders the boulder overlay with a 'the way is barred' tooltip", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const blocker = child({ id: "WF-DEP", status: "in-flight" });
    const blocked = child({ id: "k1", status: "planned", complexity: "S", depends_on: ["WF-DEP"] });
    const { container } = renderTrail(epic, [blocked, blocker]);
    expect(container.querySelector(".atlas-trail__boulder")).toBeInTheDocument();
    expect(tooltipTexts(container).some((t) => t.includes("the way is barred"))).toBe(true);
  });

  it("a blocked child whose dependency is now done renders as a plain todo waypoint, not a boulder", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const blocker = child({ id: "WF-DEP", status: "done" });
    const unblocked = child({ id: "k1", status: "planned", complexity: "S", depends_on: ["WF-DEP"] });
    const { container } = renderTrail(epic, [unblocked, blocker]);
    expect(container.querySelector(".atlas-trail__boulder")).not.toBeInTheDocument();
  });

  it("a blocked child's name-tag carries trail-tag--blocked (rose pastel) alongside trail-tag--todo", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const blocker = child({ id: "WF-DEP", status: "in-flight" });
    const blocked = child({
      id: "k1",
      title: "Barred Quest",
      status: "planned",
      complexity: "S",
      depends_on: ["WF-DEP"],
      order: 1,
    });
    const later = child({ id: "k2", title: "Later Quest", status: "planned", complexity: "S", order: 2 });
    const { container } = renderTrail(epic, [blocked, blocker, later]);
    const tag = Array.from(container.querySelectorAll(".trail-tag--todo")).find(
      (el) => el.textContent === "Barred Quest"
    );
    expect(tag).toHaveClass("trail-tag--blocked");
  });

  it("heavier children yield a longer trail than lighter ones on the same shared pxPerWeight scale", () => {
    const heavyEpic = card({ id: "WF-HEAVY", status: "in-flight" });
    const heavyKid = child({ id: "h1", status: "done", complexity: "XL" });
    const lightEpic = card({ id: "WF-LIGHT", status: "in-flight" });
    const lightKid = child({ id: "l1", status: "done", complexity: "S" });

    const heavy = renderTrail(heavyEpic, [heavyKid]);
    const light = renderTrail(lightEpic, [lightKid]);

    const heavyBeast = heavy.container.querySelector(".atlas-trail__beast")!.getAttribute("transform")!;
    const lightBeast = light.container.querySelector(".atlas-trail__beast")!.getAttribute("transform")!;
    const heavyX = Number(heavyBeast.match(/translate\(([\d.-]+),/)![1]);
    const lightX = Number(lightBeast.match(/translate\(([\d.-]+),/)![1]);
    expect(heavyX).toBeGreaterThan(lightX);
  });

  it("re-measures its own HEIGHT on ResizeObserver callback (width comes from the shared trailWidth prop, not its own measurement)", () => {
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
    const { container } = renderTrail(epic, [], { trailWidth: 500 });

    expect(capturedCallback).not.toBeNull();
    act(() => {
      capturedCallback!(
        [{ contentRect: { width: 999, height: 220 } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    const svg = container.querySelector("svg")!;
    // Width tracks the trailWidth PROP (500), never the ResizeObserver's own
    // width reading (999) — only height is self-measured.
    expect(svg.getAttribute("viewBox")).toBe("0 0 500 220");
  });

  it("never emits a non-finite viewBox even if ResizeObserver reports a non-finite height", () => {
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
    const { container } = renderTrail(epic, []);
    act(() => {
      capturedCallback!(
        [{ contentRect: { width: NaN, height: NaN } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")).not.toContain("NaN");
    for (const el of Array.from(container.querySelectorAll("circle, text"))) {
      for (const attr of ["cx", "cy", "x", "y"]) {
        const value = el.getAttribute(attr);
        if (value !== null) expect(Number.isNaN(Number(value))).toBe(false);
      }
    }
  });

  // Impl-review round 1, finding 1: the heaviest epic's beast must land
  // exactly on the HANDOFF anchor formula (trailEnd + BEAST_ANCHOR_OFFSET_PX),
  // not drift off it via an undersized/mismatched ad-hoc clamp — and its
  // Y-sample must come from the SAME x it's drawn at (never floating off
  // the wobble line).
  it("the heaviest epic's beast lands exactly on the HANDOFF anchor formula, un-clamped", () => {
    const epic = card({ id: "WF-HEAVY", status: "in-flight" });
    // laneWidth 600, pxPerWeight 20 => usable-scale headroom is generous;
    // pick a weight that keeps the raw anchor comfortably short of any
    // defensive clamp so this asserts the NORMAL (unclamped) path.
    const kid = child({ id: "k1", status: "done", complexity: "M" }); // weight 2
    const { container } = renderTrail(epic, [kid], { trailWidth: 600, pxPerWeight: 20 });

    const beastTransform = container.querySelector(".atlas-trail__beast")!.getAttribute("transform")!;
    const beastX = Number(beastTransform.match(/translate\(([\d.-]+),/)![1]);
    // trailEnd = TRAILHEAD_RESERVE_PX + 2*20; anchor = trailEnd + 26.
    const expectedTrailEnd = TRAILHEAD_RESERVE_PX + 2 * 20;
    expect(beastX).toBeCloseTo(expectedTrailEnd + 26, 5);
  });

  it("never lets the beast's own footprint overflow a trailWidth whose heaviest epic exactly saturates the shared scale", () => {
    // usable = trailWidth - BEAST_RESERVE_PX - TRAILHEAD_RESERVE_PX; a
    // pxPerWeight computed so THIS epic's total weight * pxPerWeight ==
    // usable exactly reproduces "the heaviest epic spans the trail width"
    // (EpicAtlas.tsx's own trailWidth formula) — the beast's right edge
    // (beastX + 48) must still land at/under trailWidth.
    const trailWidth = 300;
    const usable = trailWidth - BEAST_RESERVE_PX - TRAILHEAD_RESERVE_PX;
    const totalWeightUnits = 4; // one XL child
    const pxPerWeight = usable / totalWeightUnits;
    const epic = card({ id: "WF-SATURATED", status: "in-flight" });
    const kid = child({ id: "k1", status: "done", complexity: "XL" });
    const { container } = renderTrail(epic, [kid], { trailWidth, pxPerWeight });

    const beastTransform = container.querySelector(".atlas-trail__beast")!.getAttribute("transform")!;
    const beastX = Number(beastTransform.match(/translate\(([\d.-]+),/)![1]);
    expect(beastX + 48).toBeLessThanOrEqual(trailWidth + 0.01);
  });

  // Impl-review round 1, finding 3: a parked epic with ZERO done and ZERO
  // in-progress children falls all the way back to campfireX === boundaryX
  // === TRAILHEAD_RESERVE_PX — the campfire must still cut a gap in the
  // dotted line at that position, not sit on top of an un-trimmed dot.
  it("parked, all-todo epic (no done/in-progress children): the campfire still cuts a gap in the line", () => {
    const epic = card({ id: "WF-076", status: "parked" });
    const todo = child({ id: "k1", status: "planned", complexity: "M" });
    const { container } = renderTrail(epic, [todo]);

    expect(container.querySelector(".atlas-trail__campfire")).toBeInTheDocument();
    // TRAILHEAD_RESERVE_PX is the campfire's fallback position for an all-todo
    // parked epic. The line now starts under the trailhead village (left of
    // TRAILHEAD_RESERVE_PX), so a real campfire cut there splits it into a
    // lead-in piece that STARTS before that x and a resume piece that STARTS
    // after it — the gap.
    const startXs = Array.from(
      container.querySelectorAll(".atlas-trail__path")
    ).map((p) => Number(p.getAttribute("d")!.match(/^M([\d.]+)/)![1]));
    expect(startXs.some((x) => x < TRAILHEAD_RESERVE_PX)).toBe(true); // lead-in under the village
    expect(startXs.some((x) => x > TRAILHEAD_RESERVE_PX)).toBe(true); // resumes past the campfire gap
  });

  // Impl-review round 2, finding 5: the LAST-ordered child's marker sits
  // exactly at the trail's true end by construction (its segment's own
  // `end` IS `trailEnd`) — only BEAST_ANCHOR_OFFSET_PX(26) away from the
  // beast's own left edge. A centred name-tag on that marker routinely
  // crowds/overlaps the beast doodle; earlier (non-last) children have no
  // such constraint. This is true on every trail — "short trails" in the
  // review's own observation was just where it happened to be noticed.
  it("suppresses the LAST todo child's name-tag (it would crowd the beast) but keeps an earlier todo child's tag", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [
      child({ id: "k1", title: "Earlier Quest", status: "planned", complexity: "S", order: 1 }),
      child({ id: "k2", title: "Final Quest", status: "planned", complexity: "S", order: 2 }),
    ];
    const { container } = renderTrail(epic, kids, { showNames: true });

    const tags = Array.from(container.querySelectorAll(".trail-tag--todo")).map((el) => el.textContent);
    expect(tags).toContain("Earlier Quest");
    expect(tags).not.toContain("Final Quest");

    // The suppressed child's own WAYPOINT marker and full-name tooltip
    // still render fine — only the on-trail label is dropped.
    expect(container.querySelectorAll(".atlas-trail__waypoint--todo").length).toBe(2);
    expect(tooltipTexts(container).some((t) => t.startsWith("Final Quest —"))).toBe(true);
  });

  it("an in-flight epic where the LAST child is a todo (nothing done/at-hand) still suppresses only that last tag", () => {
    // A degenerate but real case: an epic that's marching (in-flight) but
    // whose only children so far are todo — the "last" child is also the
    // FIRST/only one, same geometry as the single-child case above.
    const epic = card({ id: "WF-090", status: "in-flight" });
    const solo = child({ id: "k1", title: "Only Quest", status: "planned", complexity: "M" });
    const { container } = renderTrail(epic, [solo], { showNames: true });
    expect(container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
  });

  // Feature 3 (WF-086 v3): a done child now ALSO gets an on-trail name-tag
  // — greyed (`.trail-tag--done`), same showNames gating and same
  // last-child beast-clearance suppression as the todo tag.
  describe("done child name-tags (Feature 3)", () => {
    it("a NON-last done child's name-tag shows, greyed, when showNames is true", () => {
      const epic = card({ id: "WF-085", status: "in-flight" });
      const kids = [
        child({ id: "k1", title: "Cleared Quest", status: "done", complexity: "S", order: 1 }),
        // A trailing sibling so k1 isn't the trail's last child.
        child({ id: "k2", title: "Later Quest", status: "planned", complexity: "S", order: 2 }),
      ];
      const shown = renderTrail(epic, kids, { showNames: true });
      const tag = shown.container.querySelector(".trail-tag--done");
      expect(tag).toHaveTextContent("Cleared Quest");

      const hidden = renderTrail(epic, kids, { showNames: false });
      expect(hidden.container.querySelector(".trail-tag--done")).not.toBeInTheDocument();
    });

    it("suppresses the LAST done child's name-tag (all-done epic, no todos after)", () => {
      const epic = card({ id: "WF-027", status: "in-flight" });
      const solo = child({ id: "k1", title: "Only Cleared Quest", status: "done", complexity: "S" });
      const { container } = renderTrail(epic, [solo], { showNames: true });
      expect(container.querySelector(".trail-tag--done")).not.toBeInTheDocument();
      // Marker + tooltip still render regardless.
      expect(container.querySelector(".atlas-trail__waypoint--done")).toBeInTheDocument();
    });
  });

  // Feature 3 (WF-086 v3): trail name-tags (todo AND done) are clickable
  // buttons that reuse the existing card detail drawer via onOpenCard —
  // not a new modal.
  describe("clickable trail name-tags open the card detail drawer (Feature 3)", () => {
    it("clicking a todo child's name-tag calls onOpenCard with that child's id", () => {
      const onOpenCard = vi.fn();
      const epic = card({ id: "WF-085", status: "in-flight" });
      const kids = [
        child({ id: "k1", title: "Earlier Quest", status: "planned", complexity: "S", order: 1 }),
        child({ id: "k2", title: "Later Quest", status: "planned", complexity: "S", order: 2 }),
      ];
      const { container } = renderTrail(epic, kids, { onOpenCard });
      const tag = container.querySelector(".trail-tag--todo") as HTMLButtonElement;
      expect(tag.tagName).toBe("BUTTON");
      tag.click();
      expect(onOpenCard).toHaveBeenCalledWith("k1");
    });

    it("clicking a done child's name-tag calls onOpenCard with that child's id", () => {
      const onOpenCard = vi.fn();
      const epic = card({ id: "WF-085", status: "in-flight" });
      const kids = [
        child({ id: "k1", title: "Cleared Quest", status: "done", complexity: "S", order: 1 }),
        child({ id: "k2", title: "Later Quest", status: "planned", complexity: "S", order: 2 }),
      ];
      const { container } = renderTrail(epic, kids, { onOpenCard });
      const tag = container.querySelector(".trail-tag--done") as HTMLButtonElement;
      expect(tag.tagName).toBe("BUTTON");
      tag.click();
      expect(onOpenCard).toHaveBeenCalledWith("k1");
    });

    it("clicking the AT HAND pennant calls onOpenCard with the in-progress child's id", () => {
      const onOpenCard = vi.fn();
      const epic = card({ id: "WF-085", status: "in-flight" });
      const prog = child({ id: "k1", status: "in-flight", complexity: "M", order: 1 });
      const todoAfter = child({ id: "k2", status: "planned", complexity: "S", order: 2 });
      const { container } = renderTrail(epic, [prog, todoAfter], { onOpenCard });
      const pennant = container.querySelector(".atlas-trail__pennant--athand") as HTMLButtonElement;
      expect(pennant.tagName).toBe("BUTTON");
      pennant.click();
      expect(onOpenCard).toHaveBeenCalledWith("k1");
    });

    it("when the in-progress child is the trail's last child (pennant suppressed), clicking its marker calls onOpenCard with that id", () => {
      const onOpenCard = vi.fn();
      const epic = card({ id: "WF-085", status: "in-flight" });
      const prog = child({ id: "k1", status: "in-flight", complexity: "M" });
      const { container } = renderTrail(epic, [prog], { onOpenCard });
      expect(container.querySelector(".atlas-trail__pennant--athand")).not.toBeInTheDocument();
      const marker = container.querySelector(".atlas-trail__waypoint--athand") as SVGGElement;
      marker.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      expect(onOpenCard).toHaveBeenCalledWith("k1");
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });
});
