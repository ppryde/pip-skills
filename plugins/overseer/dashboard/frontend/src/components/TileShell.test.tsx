import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import type { BoardCard } from "../api/types";
import TileShell from "./TileShell";

// RTL auto-cleans-up between tests via `test.globals: true` in
// vite.config.ts (see that file's comment) — without it, each `it()` below
// would pile its render onto the same jsdom document and `getByRole`
// queries would start matching prior tests' tiles.

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
    ...overrides,
  };
}

/** useSortable requires a DndContext + SortableContext ancestor. */
function renderTile(c: BoardCard, dragDisabled = false) {
  return render(
    <DndContext>
      <SortableContext items={[c.id]}>
        <TileShell card={c} dragDisabled={dragDisabled} />
      </SortableContext>
    </DndContext>
  );
}

describe("TileShell drag handle (Chunk 4)", () => {
  it("a planned card's handle is enabled and focusable", () => {
    renderTile(card({ id: "WF-A", status: "planned" }));
    const handle = screen.getByRole("button", { name: /drag/i });
    expect(handle).not.toBeDisabled();
    handle.focus();
    expect(handle).toHaveFocus();
  });

  it("a non-blocked in-flight card's handle is enabled", () => {
    renderTile(
      card({ id: "WF-B", status: "in-flight", stage: "implementation" })
    );
    const handle = screen.getByRole("button", { name: /drag/i });
    expect(handle).not.toBeDisabled();
  });

  it("a parked card's handle is enabled", () => {
    renderTile(card({ id: "WF-C", status: "parked" }));
    const handle = screen.getByRole("button", { name: /drag/i });
    expect(handle).not.toBeDisabled();
  });

  it("(e) a blocked tile's handle is disabled — not a drag source", () => {
    renderTile(
      card({ id: "WF-D", status: "blocked", stage: "implementation" })
    );
    const handle = screen.getByRole("button", { name: /not draggable/i });
    expect(handle).toBeDisabled();
  });

  it("(e) a done tile's handle is disabled — not a drag source", () => {
    renderTile(card({ id: "WF-E", status: "done" }));
    const handle = screen.getByRole("button", { name: /not draggable/i });
    expect(handle).toBeDisabled();
  });

  it("(e) an abandoned tile's handle is disabled — not a drag source", () => {
    renderTile(card({ id: "WF-F", status: "abandoned" }));
    const handle = screen.getByRole("button", { name: /not draggable/i });
    expect(handle).toBeDisabled();
  });

  it("a normally-draggable card's handle is disabled while a mutation is in flight", () => {
    renderTile(card({ id: "WF-G", status: "planned" }), true);
    const handle = screen.getByRole("button", { name: /drag/i });
    expect(handle).toBeDisabled();
  });
});
