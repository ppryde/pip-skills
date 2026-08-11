import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import type { BoardCard } from "../api/types";
import CardTile from "./CardTile";

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
    body: "",
    links: [],
    pr: null,
    ...overrides,
  };
}

/** useSortable (inside TileShell) requires a DndContext + SortableContext
 * ancestor — mirrors TileShell.test.tsx's `renderTile`. */
function renderCardTile(c: BoardCard, showStage = false) {
  return render(
    <DndContext>
      <SortableContext items={[c.id]}>
        <CardTile card={c} showStage={showStage} />
      </SortableContext>
    </DndContext>
  );
}

// WF-085 in-progress lane, Part B: the mobile merged "In Progress" lane
// (Lane.tsx) passes `showStage` for every card it renders, so each in-flight
// card carries its own small stage icon now that it no longer sits in its
// own dedicated stage lane. Desktop never sets `showStage` at all.
describe("<CardTile/> mobile stage icon (WF-085 in-progress lane, Part B)", () => {
  it("renders the stage icon with an accessible alt matching the stage label when showStage is true and the card has a stage", () => {
    renderCardTile(
      card({ id: "WF-A", status: "in-flight", stage: "implementation" }),
      true
    );

    const icon = screen.getByAltText("Implementation");
    expect(icon).toBeInTheDocument();
    expect(icon.tagName).toBe("IMG");
    expect(icon).toHaveAttribute("src", expect.stringMatching(/.+/));
    expect(icon).toHaveClass("card-tile__stage-icon");
  });

  it("resolves a DIFFERENT stage to its own icon + alt (not a hardcoded single stage)", () => {
    renderCardTile(
      card({ id: "WF-B", status: "blocked", stage: "awaiting-merge" }),
      true
    );

    const icon = screen.getByAltText("Awaiting Merge");
    expect(icon).toBeInTheDocument();
  });

  it("renders no stage icon when showStage is false, even for a card with a stage", () => {
    renderCardTile(
      card({ id: "WF-C", status: "in-flight", stage: "implementation" }),
      false
    );

    expect(screen.queryByAltText("Implementation")).not.toBeInTheDocument();
  });

  it("renders no stage icon for a stage-less card, even when showStage is true (defensive — backlog/parked/done/abandoned never carry a stage)", () => {
    renderCardTile(card({ id: "WF-D", status: "planned", stage: null }), true);

    expect(
      screen.queryByRole("img", { name: /.+/ })
    ).not.toBeInTheDocument();
  });
});
