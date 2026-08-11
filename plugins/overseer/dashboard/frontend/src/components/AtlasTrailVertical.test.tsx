import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import type { BoardCard, Rollup } from "../api/types";
import { beastFor } from "../board/beastName";
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
    const todo = child({ id: "k1", title: "Faraway Quest", status: "planned", complexity: "S" });

    const shown = renderColumn(epic, [todo], true);
    expect(shown.container.querySelector(".trail-tag--todo")).toHaveTextContent("Faraway Quest");

    const hidden = renderColumn(epic, [todo], false);
    expect(hidden.container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
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

  afterEach(() => {
    vi.unstubAllGlobals();
  });
});
