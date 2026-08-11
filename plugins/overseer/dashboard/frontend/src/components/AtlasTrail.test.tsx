import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import type { BoardCard, Rollup } from "../api/types";
import { beastFor } from "../board/beastName";
import { formatTokens } from "../board/formatTokens";
import { computeWindow, parseCalendarDate } from "../board/atlasGeometry";
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

function rollup(overrides: Partial<Rollup> = {}): Rollup {
  return { done: 2, total: 5, estimate: 100000, actual: 42000, ...overrides };
}

const TODAY = parseCalendarDate("2026-08-11");

function tooltipTexts(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("title")).map((t) => t.textContent ?? "");
}

describe("<AtlasTrail/>", () => {
  it("in-flight: renders an alive beast, a party token, and an uncharted-ground path", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
    const { container } = render(
      <AtlasTrail card={epic} rollup={rollup()} childCards={[]} today={TODAY} dateWindow={dateWindow} />
    );
    expect(container.querySelector(".atlas-trail__beast--alive")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__beast--slain")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__party")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__path--uncharted")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__camped")).not.toBeInTheDocument();

    const beast = beastFor("WF-085");
    expect(tooltipTexts(container)).toContain(`${beast.name} awaits (3 quests stand between)`);
  });

  it("parked: renders an alive beast, a camped marker, and NO uncharted-ground path", () => {
    const epic = card({ id: "WF-076", status: "parked", updated: "2026-07-30" });
    const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
    const { container } = render(
      <AtlasTrail card={epic} rollup={rollup({ done: 1, total: 4 })} childCards={[]} today={TODAY} dateWindow={dateWindow} />
    );
    expect(container.querySelector(".atlas-trail__beast--alive")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__camped")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__camped-label")).toHaveTextContent("camped — on hold");
    expect(container.querySelector(".atlas-trail__party")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__path--uncharted")).not.toBeInTheDocument();
  });

  it("done: renders a slain beast, gold text, and NO party token / uncharted path", () => {
    const epic = card({ id: "WF-027", status: "done", updated: "2026-08-01" });
    const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
    const { container } = render(
      <AtlasTrail card={epic} rollup={rollup({ done: 9, total: 9, actual: 210000 })} childCards={[]} today={TODAY} dateWindow={dateWindow} />
    );
    expect(container.querySelector(".atlas-trail__beast--slain")).toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__beast--alive")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__party")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__path--uncharted")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-trail__gold")).toHaveTextContent(
      `+${formatTokens(210000)} gold`
    );

    const beast = beastFor("WF-027");
    expect(tooltipTexts(container)).toContain(`${beast.name} — vanquished!`);
  });

  it("renders a waypoint per DONE child, with a 'quest cleared · <date>' tooltip, but not for undone children", () => {
    const epic = card({ id: "WF-085", status: "in-flight" });
    const doneChild = card({ id: "WF-085-1", status: "done", updated: "2026-07-16" });
    const todoChild = card({ id: "WF-085-2", status: "in-flight", updated: "2026-07-20" });
    const dateWindow = computeWindow(
      [{ created: epic.created, updated: epic.updated, children: [{ updated: doneChild.updated }] }],
      TODAY
    );
    const { container } = render(
      <AtlasTrail
        card={epic}
        rollup={rollup()}
        childCards={[doneChild, todoChild]}
        today={TODAY}
        dateWindow={dateWindow}
      />
    );
    expect(container.querySelectorAll(".atlas-trail__waypoint").length).toBe(1);
    expect(tooltipTexts(container)).toContain("quest cleared · 16 JUL");
  });

  it("re-measures on ResizeObserver callback and re-renders the SVG at the new size", () => {
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
    const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
    const { container } = render(
      <AtlasTrail card={epic} rollup={rollup()} childCards={[]} today={TODAY} dateWindow={dateWindow} />
    );

    expect(capturedCallback).not.toBeNull();
    act(() => {
      capturedCallback!(
        [{ contentRect: { width: 320, height: 120 } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 320 120");
  });

  // impl-review finding: defense-in-depth against a pathological
  // ResizeObserver measurement (a non-finite contentRect width/height —
  // not something a real browser is expected to report, but AtlasTrail
  // shouldn't trust that blindly). The primary NaN source (a malformed
  // `dateWindow`) is closed at pctForDate itself (atlasGeometry.ts), but a
  // non-finite SIZE measurement feeds `width`/`laneHeight` directly into
  // every x/y/cx/cy this component computes, bypassing that guard entirely.
  it("never emits a non-finite viewBox even if ResizeObserver reports a non-finite size", () => {
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
    const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
    const { container } = render(
      <AtlasTrail card={epic} rollup={rollup()} childCards={[]} today={TODAY} dateWindow={dateWindow} />
    );

    act(() => {
      capturedCallback!(
        [{ contentRect: { width: NaN, height: NaN } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    const svg = container.querySelector("svg")!;
    const viewBox = svg.getAttribute("viewBox")!;
    expect(viewBox).not.toContain("NaN");
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
