import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { BoardCard, Rollup } from "../api/types";
import { beastFor } from "../board/beastName";
import AtlasRailCard from "./AtlasRailCard";

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
    created: "2026-07-01",
    updated: "2026-07-10",
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

describe("<AtlasRailCard/>", () => {
  it("renders the WF-id and rarity stars from complexity", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-085", complexity: "M" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(screen.getByText("WF-085")).toBeInTheDocument();
    expect(container.querySelectorAll(".atlas-rail-card__star--filled").length).toBe(2);
  });

  it("renders the 'vs <Beast>' line using the same beastFor generator", () => {
    render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(screen.getByText(`vs ${beastFor("WF-085").name}`)).toBeInTheDocument();
  });

  it("renders quest count and gold from the rollup", () => {
    render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup({ done: 3, total: 7, actual: 15000 })}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(screen.getByText("3/7 quests")).toBeInTheDocument();
    expect(screen.getByText(/15k/)).toBeInTheDocument();
  });

  it("marks a done epic's title with the done modifier class", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-027", status: "done" })}
        rollup={rollup({ done: 9, total: 9 })}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(container.querySelector(".atlas-rail-card--done")).toBeInTheDocument();
    expect(container.querySelector(".atlas-rail-card__title--done")).toBeInTheDocument();
  });

  it("marks a parked epic with the parked modifier class", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-076", status: "parked" })}
        rollup={rollup({ done: 1, total: 4 })}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(container.querySelector(".atlas-rail-card--parked")).toBeInTheDocument();
  });

  it("renders a lock chip only when blockedOn is non-empty", () => {
    const { container, rerender } = render(
      <AtlasRailCard
        card={card({ id: "WF-090" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(container.querySelector(".atlas-rail-card__lock")).not.toBeInTheDocument();

    rerender(
      <AtlasRailCard
        card={card({ id: "WF-090" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
        blockedOn={["WF-085"]}
      />
    );
    expect(screen.getByText(/🔒/)).toBeInTheDocument();
    expect(screen.getByText(/WF-085/)).toBeInTheDocument();
  });

  it("renders no expand button when the epic has no children", () => {
    render(
      <AtlasRailCard
        card={card({ id: "WF-090" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a Role-A styled expand button (NOT the legacy epic-card__expand class) when children exist", () => {
    render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[card({ id: "WF-085-1" })]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    const button = screen.getByRole("button");
    expect(button).toHaveClass("atlas-rail-card__expand");
    expect(button).not.toHaveClass("epic-card__expand");
  });

  it("toggles expand via onToggleExpand without firing onOpen (stopPropagation)", () => {
    const onToggleExpand = vi.fn();
    const onOpen = vi.fn();
    render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[card({ id: "WF-085-1" })]}
        expanded={false}
        onToggleExpand={onToggleExpand}
        onOpen={onOpen}
      />
    );
    screen.getByRole("button").click();
    expect(onToggleExpand).toHaveBeenCalledWith("WF-085");
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("clicking the card body (outside the expand button) fires onOpen", () => {
    const onOpen = vi.fn();
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={onOpen}
      />
    );
    (container.querySelector(".atlas-rail-card") as HTMLElement).click();
    expect(onOpen).toHaveBeenCalledWith("WF-085");
  });

  it("keeps the 'vs beast' line and chips row present (condensed set) even though they'll be CSS-hidden on mobile", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(container.querySelector(".atlas-rail-card__vs")).toBeInTheDocument();
    expect(container.querySelector(".atlas-rail-card__chips")).toBeInTheDocument();
  });

  // impl-review finding: HANDOFF's condensed mobile set keeps "progress
  // track + n/m count" visible and hides only the "vs beast" line and the
  // gold/lock chips — but styles.css hides `.atlas-rail-card__chips` as a
  // whole with `display:none`, so a count nested INSIDE that wrapper would
  // vanish right along with it. The count must be a class the mobile hide
  // rule never reaches — i.e. NOT a descendant of `.atlas-rail-card__chips`.
  it("renders the n/m count OUTSIDE the chips wrapper, so the mobile chips hide rule can never take it with it", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup({ done: 3, total: 7 })}
        childCards={[]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    const chips = container.querySelector(".atlas-rail-card__chips");
    const count = container.querySelector(".atlas-rail-card__count");
    expect(count).toBeInTheDocument();
    expect(chips).toBeInTheDocument();
    expect(chips!.contains(count)).toBe(false);
  });

  // WF-086 v2: the checklist order now matches the TRAIL's own order
  // (done -> in-progress -> todo, by board `order` within each group) —
  // not the old date-sorted order — so the rail card's expanded list and
  // its own trail row never disagree about sequence.
  it("orders the expanded checklist done -> in-progress -> todo, by board `order` within each group", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[
          card({ id: "WF-085-3", title: "Todo", status: "planned", order: 1 }),
          card({ id: "WF-085-2", title: "Second Done", status: "done", updated: "2026-08-06", order: 2 }),
          card({ id: "WF-085-1", title: "First Done", status: "done", updated: "2026-07-31", order: 1 }),
        ]}
        expanded={true}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    const rows = container.querySelectorAll(".atlas-rail-card__subquest");
    expect(Array.from(rows).map((r) => r.textContent)).toEqual([
      expect.stringContaining("First Done"),
      expect.stringContaining("Second Done"),
      expect.stringContaining("Todo"),
    ]);
    expect(rows[0]).toHaveClass("atlas-rail-card__subquest--done");
    expect(rows[0]).toHaveTextContent("31 JUL");
  });

  it("renders no sub-quest list when collapsed, even with children present", () => {
    const { container } = render(
      <AtlasRailCard
        card={card({ id: "WF-085" })}
        rollup={rollup()}
        childCards={[card({ id: "WF-085-1" })]}
        expanded={false}
        onToggleExpand={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(container.querySelector(".atlas-rail-card__subquests")).not.toBeInTheDocument();
  });

  describe("checklist row styling per status (HANDOFF's checklist wheel)", () => {
    it("done: accent ✓ checkbox and the real date stamp", () => {
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={[card({ id: "k1", title: "Cleared", status: "done", updated: "2026-08-06" })]}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
        />
      );
      const row = container.querySelector(".atlas-rail-card__subquest")!;
      expect(row.querySelector(".atlas-rail-card__checkbox")).toHaveTextContent("✓");
      expect(row.querySelector(".atlas-rail-card__subquest-date")).toHaveTextContent("6 AUG");
    });

    it("abandoned: dark box '†' glyph, struck-through title, real date — excluded from the done modifier", () => {
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={[card({ id: "k1", title: "Fallen", status: "abandoned", updated: "2026-07-20" })]}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
        />
      );
      const row = container.querySelector(".atlas-rail-card__subquest")!;
      expect(row).toHaveClass("atlas-rail-card__subquest--abandoned");
      expect(row).not.toHaveClass("atlas-rail-card__subquest--done");
      expect(row.querySelector(".atlas-rail-card__checkbox")).toHaveTextContent("†");
      expect(row.querySelector(".atlas-rail-card__subquest-title")).toHaveClass(
        "atlas-rail-card__subquest-title--abandoned"
      );
      expect(row.querySelector(".atlas-rail-card__subquest-date")).toHaveTextContent("20 JUL");
    });

    it("blocked (open depends_on): rose border + ⛔ checkbox glyph", () => {
      const cardsById = new Map([
        ["WF-DEP", card({ id: "WF-DEP", status: "in-flight" })],
      ]);
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={[card({ id: "k1", title: "Barred", status: "planned", depends_on: ["WF-DEP"] })]}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
          cardsById={cardsById}
        />
      );
      const row = container.querySelector(".atlas-rail-card__subquest")!;
      expect(row).toHaveClass("atlas-rail-card__subquest--blocked");
      expect(row.querySelector(".atlas-rail-card__checkbox")).toHaveTextContent("⛔");
    });

    it("todo: no honest date — the stamp shows ★weight instead", () => {
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={[
            card({ id: "k1", title: "Ahead", status: "planned", complexity: "L", updated: "2026-08-06" }),
          ]}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
        />
      );
      const row = container.querySelector(".atlas-rail-card__subquest")!;
      expect(row.querySelector(".atlas-rail-card__checkbox")).toHaveTextContent("");
      expect(row.querySelector(".atlas-rail-card__subquest-date")).toHaveTextContent("★★★");
      expect(row.querySelector(".atlas-rail-card__subquest-date")).not.toHaveTextContent("AUG");
    });
  });

  describe("checklist wheel scroll fades", () => {
    function stubScrollMetrics(scrollHeight: number, clientHeight: number, scrollTop = 0) {
      vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(scrollHeight);
      vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(clientHeight);
      vi.spyOn(HTMLElement.prototype, "scrollTop", "get").mockReturnValue(scrollTop);
    }

    afterEach(() => {
      vi.restoreAllMocks();
    });

    function manyChildren(n: number) {
      return Array.from({ length: n }, (_, i) =>
        card({ id: `k${i}`, title: `Quest ${i}`, status: "planned", order: i })
      );
    }

    it("shows a bottom fade (not a top fade) when content overflows and is scrolled to the top", () => {
      stubScrollMetrics(400, 132, 0);
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={manyChildren(10)}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
        />
      );
      const list = container.querySelector(".atlas-rail-card__subquests")!;
      expect(list).toHaveClass("atlas-rail-card__subquests--fade-bottom");
      expect(list).not.toHaveClass("atlas-rail-card__subquests--fade-top");
    });

    it("shows both fades mid-scroll, and only the top fade once scrolled to the bottom", () => {
      stubScrollMetrics(400, 132, 50);
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={manyChildren(10)}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
        />
      );
      const list = container.querySelector(".atlas-rail-card__subquests")!;
      fireEvent.scroll(list);
      expect(list).toHaveClass("atlas-rail-card__subquests--fade-top");
      expect(list).toHaveClass("atlas-rail-card__subquests--fade-bottom");

      stubScrollMetrics(400, 132, 268); // 268 + 132 === 400 -> scrolled to true bottom
      fireEvent.scroll(list);
      expect(list).toHaveClass("atlas-rail-card__subquests--fade-top");
      expect(list).not.toHaveClass("atlas-rail-card__subquests--fade-bottom");
    });

    it("shows neither fade when the content doesn't overflow the cap", () => {
      stubScrollMetrics(80, 132, 0);
      const { container } = render(
        <AtlasRailCard
          card={card({ id: "WF-085" })}
          rollup={rollup()}
          childCards={manyChildren(2)}
          expanded={true}
          onToggleExpand={vi.fn()}
          onOpen={vi.fn()}
        />
      );
      const list = container.querySelector(".atlas-rail-card__subquests")!;
      expect(list).not.toHaveClass("atlas-rail-card__subquests--fade-top");
      expect(list).not.toHaveClass("atlas-rail-card__subquests--fade-bottom");
    });
  });
});
