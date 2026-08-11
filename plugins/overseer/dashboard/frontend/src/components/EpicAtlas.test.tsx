import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { Board, BoardCard } from "../api/types";
import EpicAtlas from "./EpicAtlas";

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

function board(cards: BoardCard[]): Board {
  return { project: "test", cards, sprints: [], quarantined: [], label_colors: {} };
}

describe("<EpicAtlas/>", () => {
  it("renders one row per is_epic card with a non-null rollup, sorted by created ascending", () => {
    const cards = [
      card({ id: "WF-090", is_epic: true, rollup: { done: 0, total: 5, estimate: null, actual: 0 }, created: "2026-08-08" }),
      card({ id: "WF-027", is_epic: true, rollup: { done: 9, total: 9, estimate: null, actual: 210000 }, created: "2026-07-14" }),
      card({ id: "WF-058", is_epic: true, rollup: { done: 6, total: 6, estimate: null, actual: 74000 }, created: "2026-07-20" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
    const rails = container.querySelectorAll(".atlas-rail-card");
    expect(rails.length).toBe(3);
    expect(Array.from(rails).map((r) => r.getAttribute("data-card-id"))).toEqual([
      "WF-027",
      "WF-058",
      "WF-090",
    ]);
  });

  it("excludes an is_epic card with a null rollup", () => {
    const cards = [
      card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } }),
      card({ id: "WF-BAD", is_epic: true, rollup: null }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
    expect(container.querySelector('[data-card-id="WF-BAD"]')).not.toBeInTheDocument();
    expect(container.querySelector('[data-card-id="WF-027"]')).toBeInTheDocument();
  });

  it("excludes non-epic cards entirely", () => {
    const cards = [
      card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } }),
      card({ id: "WF-027-1", is_epic: false, parent: "WF-027" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
    expect(container.querySelectorAll(".atlas-rail-card").length).toBe(1);
  });

  it("renders the empty-state invitation when there are no epics", () => {
    render(<EpicAtlas board={board([])} onOpenCard={vi.fn()} />);
    expect(
      screen.getByText("No sagas yet — give a quest children and it becomes a campaign.")
    ).toBeInTheDocument();
  });

  it("renders no toolbar in the empty state", () => {
    const { container } = render(<EpicAtlas board={board([])} onOpenCard={vi.fn()} />);
    expect(container.querySelector(".atlas-toolbar")).not.toBeInTheDocument();
  });

  // Killed from v1 (HANDOFF): date axis, weekly ticks, TODAY pennant, and
  // the pace-projection honesty footnote must never appear in v2.
  it("never renders the v1 date-axis / TODAY signpost / projection footnote", () => {
    const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
    const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} />);
    expect(container.querySelector(".atlas-chart__axis")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-chart__today")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-chart__footnote")).not.toBeInTheDocument();
  });

  it("passes an unmet depends_on target through as blockedOn on the rail card", () => {
    const cards = [
      card({ id: "WF-090", is_epic: true, rollup: { done: 0, total: 1, estimate: null, actual: 0 }, depends_on: ["WF-085"] }),
      card({ id: "WF-085", status: "in-flight" }),
    ];
    render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
    expect(screen.getByText(/🔒/)).toBeInTheDocument();
    expect(screen.getByText(/WF-085/, { selector: ".atlas-rail-card__lock" })).toBeInTheDocument();
  });

  it("omits blockedOn once the dependency target is done", () => {
    const cards = [
      card({ id: "WF-090", is_epic: true, rollup: { done: 0, total: 1, estimate: null, actual: 0 }, depends_on: ["WF-085"] }),
      card({ id: "WF-085", status: "done" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
    expect(container.querySelector(".atlas-rail-card__lock")).not.toBeInTheDocument();
  });

  it("opens the drawer via onOpenCard when a rail card body is clicked", () => {
    const onOpenCard = vi.fn();
    const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
    const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={onOpenCard} />);
    (container.querySelector('[data-card-id="WF-027"]') as HTMLElement).click();
    expect(onOpenCard).toHaveBeenCalledWith("WF-027");
  });

  it("has no per-row/lane element with a scroll-suggestively-named class, alongside .atlas-chart (725ddea naming-convention guard)", () => {
    const cards = [
      card({ id: "WF-A", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } }),
      card({ id: "WF-B", is_epic: true, rollup: { done: 0, total: 3, estimate: null, actual: 0 } }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);

    expect(container.querySelectorAll(".atlas-chart").length).toBe(1);

    for (const el of Array.from(container.querySelectorAll<HTMLElement>("*"))) {
      if (el.classList.contains("atlas-chart")) continue;
      for (const cls of Array.from(el.classList)) {
        expect(cls).not.toMatch(/scroll/i);
      }
    }
  });

  describe("vanquished-epics toggle", () => {
    function vanquishedBoard() {
      return board([
        card({ id: "WF-DONE", is_epic: true, status: "done", rollup: { done: 3, total: 3, estimate: null, actual: 0 }, created: "2026-07-01" }),
        card({ id: "WF-LIVE", is_epic: true, status: "in-flight", rollup: { done: 1, total: 3, estimate: null, actual: 0 }, created: "2026-07-10" }),
      ]);
    }

    it("defaults to HIDE — a done epic never renders", () => {
      const { container } = render(<EpicAtlas board={vanquishedBoard()} onOpenCard={vi.fn()} />);
      expect(container.querySelector('[data-card-id="WF-DONE"]')).not.toBeInTheDocument();
      expect(container.querySelector('[data-card-id="WF-LIVE"]')).toBeInTheDocument();
    });

    it("Show reveals done epics, sorted LAST", () => {
      const { container } = render(<EpicAtlas board={vanquishedBoard()} onOpenCard={vi.fn()} />);
      fireEvent.click(screen.getByRole("tab", { name: /🏆 show/i }));
      const rails = container.querySelectorAll(".atlas-rail-card");
      expect(Array.from(rails).map((r) => r.getAttribute("data-card-id"))).toEqual(["WF-LIVE", "WF-DONE"]);
    });
  });

  describe("quest-names toggle", () => {
    it("defaults to shown — a todo child's name-tag is visible", () => {
      const cards = [
        card({ id: "WF-EPIC", is_epic: true, status: "in-flight", rollup: { done: 0, total: 1, estimate: null, actual: 0 } }),
        card({ id: "WF-EPIC-1", parent: "WF-EPIC", status: "planned", title: "Faraway Quest", complexity: "S" }),
      ];
      const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
      expect(container.querySelector(".trail-tag--todo")).toBeInTheDocument();
    });

    it("Hush hides the todo name-tag", () => {
      const cards = [
        card({ id: "WF-EPIC", is_epic: true, status: "in-flight", rollup: { done: 0, total: 1, estimate: null, actual: 0 } }),
        card({ id: "WF-EPIC-1", parent: "WF-EPIC", status: "planned", title: "Faraway Quest", complexity: "S" }),
      ];
      const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
      fireEvent.click(screen.getByRole("tab", { name: /hush/i }));
      expect(container.querySelector(".trail-tag--todo")).not.toBeInTheDocument();
    });
  });

  it("shares ONE pxPerWeight scale across rows — two epics with equal total child weight end at the same beast x", () => {
    const cards = [
      card({ id: "WF-A", is_epic: true, status: "in-flight", rollup: { done: 1, total: 1, estimate: null, actual: 0 }, created: "2026-07-01" }),
      card({ id: "WF-A-1", parent: "WF-A", status: "done", complexity: "M" }),
      card({ id: "WF-B", is_epic: true, status: "in-flight", rollup: { done: 1, total: 1, estimate: null, actual: 0 }, created: "2026-07-02" }),
      card({ id: "WF-B-1", parent: "WF-B", status: "done", complexity: "M" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
    const beasts = Array.from(container.querySelectorAll(".atlas-trail__beast"));
    expect(beasts.length).toBe(2);
    const xs = beasts.map((b) => Number(b.getAttribute("transform")!.match(/translate\(([\d.-]+),/)![1]));
    expect(xs[0]).toBeCloseTo(xs[1], 5);
  });

  describe("mobile Down orientation (HANDOFF: shipped in production, <=720px only)", () => {
    const originalMatchMedia = window.matchMedia;

    afterEach(() => {
      window.matchMedia = originalMatchMedia;
      vi.restoreAllMocks();
    });

    function stubViewport(matches: boolean) {
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      })) as unknown as typeof window.matchMedia;
    }

    it("renders columns (not rows) once Down is selected on a <=720px viewport", () => {
      stubViewport(true);
      const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
      const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} />);

      fireEvent.click(screen.getByRole("tab", { name: /⟱ down/i }));

      expect(container.querySelector(".atlas-chart__columns")).toBeInTheDocument();
      expect(container.querySelector(".atlas-chart__rows")).not.toBeInTheDocument();
      expect(container.querySelector(".atlas-chart--down")).toBeInTheDocument();
    });

    it("Down stays inert on a desktop (>720px) viewport — still renders rows", () => {
      stubViewport(false);
      const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
      const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} />);

      fireEvent.click(screen.getByRole("tab", { name: /⟱ down/i }));

      expect(container.querySelector(".atlas-chart__rows")).toBeInTheDocument();
      expect(container.querySelector(".atlas-chart__columns")).not.toBeInTheDocument();
    });

    // Impl-review round 1, finding 2: the ResizeObserver used to attach
    // once to whichever column was active when the effect last RAN (a
    // stale closure), and never re-pointed itself after a swipe — content
    // growth on the NEWLY active column, with no accompanying scroll
    // event, left the pinned height stale. This locks in the fix: after a
    // swipe (a scroll event moves the nearest-to-centre column), the
    // observer is re-targeted at the new active column, and a resize on
    // THAT column (fired with no scroll at all) updates the pinned height.
    it("re-targets the ResizeObserver to the new active column after a swipe — content growth with no scroll still updates the pinned height", () => {
      stubViewport(true);

      // AtlasTrailVertical.tsx constructs its OWN ResizeObserver instances
      // too (unrelated column-width self-measurement) — tracking
      // observe/unobserve PER INSTANCE (not one shared array/callback) is
      // what lets the test find and fire specifically the instance this
      // effect owns, rather than accidentally firing an unrelated one.
      const instances: { el: HTMLElement | null; cb: ResizeObserverCallback }[] = [];
      class MockResizeObserver {
        private entry: { el: HTMLElement | null; cb: ResizeObserverCallback };
        constructor(cb: ResizeObserverCallback) {
          this.entry = { el: null, cb };
          instances.push(this.entry);
        }
        observe(el: HTMLElement) {
          this.entry.el = el;
        }
        unobserve() {
          this.entry.el = null;
        }
        disconnect() {}
      }
      vi.stubGlobal("ResizeObserver", MockResizeObserver);

      const observedColumnEls = () =>
        instances.map((i) => i.el).filter((el): el is HTMLElement => el != null && el.dataset.columnIndex != null);

      let nearestIndex = 0;
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
        this: HTMLElement
      ) {
        const base = { top: 0, bottom: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) };
        if (!this.dataset.columnIndex) {
          return { left: 0, right: 100, width: 100, ...base } as DOMRect;
        }
        const isNearest = this.dataset.columnIndex === String(nearestIndex);
        return { left: isNearest ? 0 : 1000, right: isNearest ? 100 : 1100, width: 100, ...base } as DOMRect;
      });

      const scrollHeights: Record<string, number> = { "0": 300, "1": 300 };
      vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (
        this: HTMLElement
      ) {
        return scrollHeights[this.dataset.columnIndex ?? ""] ?? 0;
      });

      const cards = [
        card({ id: "WF-A", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } }),
        card({ id: "WF-B", is_epic: true, rollup: { done: 0, total: 3, estimate: null, actual: 0 } }),
      ];
      const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} />);
      fireEvent.click(screen.getByRole("tab", { name: /⟱ down/i }));

      const columnsEl = container.querySelector(".atlas-chart__columns") as HTMLElement;
      expect(columnsEl.style.height).toBe("300px");
      expect(observedColumnEls().map((el) => el.dataset.columnIndex)).toEqual(["0"]);

      // Swipe: column 1 becomes nearest-to-centre.
      nearestIndex = 1;
      fireEvent.scroll(columnsEl);

      const nowObserved = observedColumnEls();
      expect(nowObserved.map((el) => el.dataset.columnIndex)).toEqual(["1"]);

      // Column 1's checklist expands — no scroll event, only the
      // (re-targeted) ResizeObserver firing on the instance that's
      // specifically watching column 1.
      scrollHeights["1"] = 480;
      const activeInstance = instances.find((i) => i.el === nowObserved[0])!;
      act(() => {
        activeInstance.cb([], {} as ResizeObserver);
      });

      expect(columnsEl.style.height).toBe("480px");
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });
});
