import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Board, BoardCard } from "../api/types";
import { computeWindow, parseCalendarDate, pctForDate } from "../board/atlasGeometry";
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

const TODAY = parseCalendarDate("2026-08-11");

describe("<EpicAtlas/>", () => {
  it("renders one row per is_epic card with a non-null rollup, sorted by created ascending", () => {
    const cards = [
      card({ id: "WF-090", is_epic: true, rollup: { done: 0, total: 5, estimate: null, actual: 0 }, created: "2026-08-08" }),
      card({ id: "WF-027", is_epic: true, rollup: { done: 9, total: 9, estimate: null, actual: 210000 }, created: "2026-07-14" }),
      card({ id: "WF-058", is_epic: true, rollup: { done: 6, total: 6, estimate: null, actual: 74000 }, created: "2026-07-20" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} today={TODAY} />);
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
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} today={TODAY} />);
    expect(container.querySelector('[data-card-id="WF-BAD"]')).not.toBeInTheDocument();
    expect(container.querySelector('[data-card-id="WF-027"]')).toBeInTheDocument();
  });

  it("excludes non-epic cards entirely", () => {
    const cards = [
      card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } }),
      card({ id: "WF-027-1", is_epic: false, parent: "WF-027" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} today={TODAY} />);
    expect(container.querySelectorAll(".atlas-rail-card").length).toBe(1);
  });

  // WF-086 chunk 10: the mobile responsive layer makes `.atlas-chart` the
  // ONE horizontal scroller (styles.css's `725ddea` invariant, same one the
  // board itself encodes). This is a structural regression guard, not a CSS
  // test (jsdom has no real layout) — it fails the moment any future change
  // gives a per-row/lane element its own independent scroll class, which is
  // exactly the bug 725ddea fixed on the board.
  it("is the sole scroll-classed element in its subtree (725ddea one-scroller invariant)", () => {
    const cards = [
      card({ id: "WF-A", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } }),
      card({ id: "WF-B", is_epic: true, rollup: { done: 0, total: 3, estimate: null, actual: 0 } }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} today={TODAY} />);

    expect(container.querySelectorAll(".atlas-chart").length).toBe(1);

    for (const el of Array.from(container.querySelectorAll<HTMLElement>("*"))) {
      if (el.classList.contains("atlas-chart")) continue;
      for (const cls of Array.from(el.classList)) {
        expect(cls).not.toMatch(/scroll/i);
      }
    }
  });

  it("renders the empty-state invitation when there are no epics", () => {
    render(<EpicAtlas board={board([])} onOpenCard={vi.fn()} today={TODAY} />);
    expect(
      screen.getByText("No sagas yet — give a quest children and it becomes a campaign.")
    ).toBeInTheDocument();
  });

  it("renders the legend and an honest projection footnote once there are epics", () => {
    const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
    const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} today={TODAY} />);
    expect(container.querySelector(".atlas-chart__legend")).toBeInTheDocument();
    const footnote = container.querySelector(".atlas-chart__footnote");
    expect(footnote).toBeInTheDocument();
    // HANDOFF's explicit honesty requirement: the ledger keeps no due
    // dates, so uncharted ground must never read as a promise.
    expect(footnote).toHaveTextContent(/pace-guessed, never promised/i);
  });

  it("renders no legend/footnote in the empty state", () => {
    const { container } = render(<EpicAtlas board={board([])} onOpenCard={vi.fn()} today={TODAY} />);
    expect(container.querySelector(".atlas-chart__legend")).not.toBeInTheDocument();
    expect(container.querySelector(".atlas-chart__footnote")).not.toBeInTheDocument();
  });

  it("positions the TODAY signpost using pctForDate over the computed window", () => {
    const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 9, total: 9, estimate: null, actual: 0 }, created: "2026-07-14", updated: "2026-08-01" });
    const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} today={TODAY} />);

    const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
    const expectedPct = pctForDate(TODAY, dateWindow);

    const today = container.querySelector(".atlas-chart__today") as HTMLElement;
    expect(today).toBeInTheDocument();
    expect(today.style.left).toBe(
      `calc(var(--rail) + (100% - var(--rail)) * ${expectedPct / 100})`
    );
  });

  it("passes an unmet depends_on target through as blockedOn on the rail card", () => {
    const cards = [
      card({ id: "WF-090", is_epic: true, rollup: { done: 0, total: 1, estimate: null, actual: 0 }, depends_on: ["WF-085"] }),
      card({ id: "WF-085", status: "in-flight" }),
    ];
    render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} today={TODAY} />);
    expect(screen.getByText(/🔒/)).toBeInTheDocument();
    expect(screen.getByText(/WF-085/, { selector: ".atlas-rail-card__lock" })).toBeInTheDocument();
  });

  it("omits blockedOn once the dependency target is done", () => {
    const cards = [
      card({ id: "WF-090", is_epic: true, rollup: { done: 0, total: 1, estimate: null, actual: 0 }, depends_on: ["WF-085"] }),
      card({ id: "WF-085", status: "done" }),
    ];
    const { container } = render(<EpicAtlas board={board(cards)} onOpenCard={vi.fn()} today={TODAY} />);
    expect(container.querySelector(".atlas-rail-card__lock")).not.toBeInTheDocument();
  });

  it("opens the drawer via onOpenCard when a rail card body is clicked", () => {
    const onOpenCard = vi.fn();
    const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
    const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={onOpenCard} today={TODAY} />);
    (container.querySelector('[data-card-id="WF-027"]') as HTMLElement).click();
    expect(onOpenCard).toHaveBeenCalledWith("WF-027");
  });

  describe("mount scroll centring", () => {
    let widthSpy: ReturnType<typeof vi.spyOn>;
    let heightSpy: ReturnType<typeof vi.spyOn>;

    afterEach(() => {
      widthSpy?.mockRestore();
      heightSpy?.mockRestore();
    });

    it("sets scrollLeft to centre today, clamped to >= 0", () => {
      widthSpy = vi
        .spyOn(HTMLElement.prototype, "scrollWidth", "get")
        .mockReturnValue(2000);
      heightSpy = vi
        .spyOn(HTMLElement.prototype, "clientWidth", "get")
        .mockReturnValue(500);

      const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 }, created: "2026-07-14", updated: "2026-08-01" });
      const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} today={TODAY} />);

      const dateWindow = computeWindow([{ created: epic.created, updated: epic.updated }], TODAY);
      const pct = pctForDate(TODAY, dateWindow);
      const expected = Math.max(0, (pct / 100) * 2000 - 500 / 2);

      const chart = container.querySelector(".atlas-chart") as HTMLElement;
      expect(chart.scrollLeft).toBe(expected);
    });

    it("clamps a negative target to 0", () => {
      widthSpy = vi
        .spyOn(HTMLElement.prototype, "scrollWidth", "get")
        .mockReturnValue(100);
      heightSpy = vi
        .spyOn(HTMLElement.prototype, "clientWidth", "get")
        .mockReturnValue(2000);

      const epic = card({ id: "WF-027", is_epic: true, rollup: { done: 1, total: 2, estimate: null, actual: 0 } });
      const { container } = render(<EpicAtlas board={board([epic])} onOpenCard={vi.fn()} today={TODAY} />);

      const chart = container.querySelector(".atlas-chart") as HTMLElement;
      expect(chart.scrollLeft).toBe(0);
    });
  });
});
