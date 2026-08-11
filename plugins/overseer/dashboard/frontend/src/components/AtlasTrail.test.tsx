import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import type { BoardCard, Rollup } from "../api/types";
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
  overrides: Partial<{ rollup: Rollup; showNames: boolean; laneWidth: number; pxPerWeight: number }> = {}
) {
  const cardsById = new Map<string, BoardCard>([epic, ...childCards].map((c) => [c.id, c]));
  return render(
    <AtlasTrail
      card={epic}
      rollup={overrides.rollup ?? rollup()}
      childCards={childCards}
      cardsById={cardsById}
      pxPerWeight={overrides.pxPerWeight ?? PX_PER_WEIGHT}
      laneWidth={overrides.laneWidth ?? 600}
      showNames={overrides.showNames ?? true}
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
    const prog = child({ id: "k1", status: "in-flight", complexity: "M" });
    const { container } = renderTrail(epic, [prog]);
    expect(container.querySelector(".at-hand-ring")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__pennant--athand")).toHaveTextContent("◆ AT HAND");
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

  it("todo child: renders a faded hollow waypoint, and a name-tag only when showNames is true", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const todo = child({ id: "k1", title: "Faraway Quest", status: "planned", complexity: "S" });

    const shown = renderTrail(epic, [todo], { showNames: true });
    expect(shown.container.querySelector(".atlas-trail__waypoint--todo")).toBeInTheDocument();
    expect(shown.container.querySelector(".trail-tag--todo")).toHaveTextContent("Faraway Quest");

    const hidden = renderTrail(epic, [todo], { showNames: false });
    expect(hidden.container.querySelector(".atlas-trail__waypoint--todo")).toBeInTheDocument();
    expect(hidden.container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
  });

  it("todo child name-tags alternate between two vertical tiers so adjacent tags never collide", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const kids = [
      child({ id: "k1", title: "First", status: "planned", complexity: "S", order: 1 }),
      child({ id: "k2", title: "Second", status: "planned", complexity: "S", order: 2 }),
    ];
    const { container } = renderTrail(epic, kids, { showNames: true });
    const tags = Array.from(container.querySelectorAll(".trail-tag--todo"));
    expect(tags.length).toBe(2);
    expect(tags[0].className).not.toBe(tags[1].className);
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

  it("re-measures its own HEIGHT on ResizeObserver callback (width comes from the shared laneWidth prop, not its own measurement)", () => {
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
    const { container } = renderTrail(epic, [], { laneWidth: 500 });

    expect(capturedCallback).not.toBeNull();
    act(() => {
      capturedCallback!(
        [{ contentRect: { width: 999, height: 220 } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    const svg = container.querySelector("svg")!;
    // Width tracks the laneWidth PROP (500), never the ResizeObserver's own
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

  afterEach(() => {
    vi.unstubAllGlobals();
  });
});
