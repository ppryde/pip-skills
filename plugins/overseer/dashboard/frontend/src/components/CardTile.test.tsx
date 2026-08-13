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
function renderCardTile(c: BoardCard) {
  return render(
    <DndContext>
      <SortableContext items={[c.id]}>
        <CardTile card={c} />
      </SortableContext>
    </DndContext>
  );
}

// Task 5: the old mobile-only `showStage` prop/icon is gone — TileShell now
// renders ONE always-on, interactive lifecycle icon (InfoTooltip-wrapped)
// for every card, on every lane, desktop and mobile alike. The bucket label
// is exposed as the trigger's `aria-label` (`iconKeyLabel(cardIconKey(...))`
// — see laneIcons.ts), so tests find it via `getByLabelText` rather than
// `getByAltText` (the `<img>` itself is `aria-hidden`, decorative).
describe("<CardTile/> lifecycle icon (task 5)", () => {
  it("renders the lifecycle icon labelled with the card's stage when it has one", () => {
    renderCardTile(
      card({ id: "WF-A", status: "in-flight", stage: "implementation" })
    );

    const trigger = screen.getByLabelText("Implementation");
    expect(trigger).toBeInTheDocument();
    const icon = trigger.querySelector("img")!;
    expect(icon).toHaveAttribute("src", expect.stringMatching(/.+/));
    expect(icon).toHaveClass("card-tile__lifecycle-icon");
  });

  it("resolves a DIFFERENT stage to its own icon + label (not a hardcoded single stage)", () => {
    renderCardTile(
      card({ id: "WF-B", status: "blocked", stage: "awaiting-merge" })
    );

    expect(screen.getByLabelText("Awaiting Merge")).toBeInTheDocument();
  });

  it("still renders the lifecycle icon for a stage-less card, labelled with its bucket", () => {
    renderCardTile(card({ id: "WF-D", status: "planned", stage: null }));

    expect(screen.getByLabelText("Backlog")).toBeInTheDocument();
  });
});
