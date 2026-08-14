import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import type { BoardCard } from "../api/types";
import EpicCard from "./EpicCard";

function card(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    // Defaults title to the id itself (Task 1's `card()` convention) — the
    // sub-quest-row assertions below look up children by their bare id text
    // (e.g. `getByText("K2")`), not a "Title K2"-shaped label.
    title: overrides.id,
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
function renderEpic(ui: React.ReactElement) {
  return render(
    <DndContext>
      <SortableContext items={["WF-086", "WF-0"]}>{ui}</SortableContext>
    </DndContext>
  );
}

describe("<EpicCard/> bottom bar + inline sub-quest log", () => {
  it("shows the quest count and expands the sub-quest log", () => {
    const epic = card({ id: "WF-086", is_epic: true, rollup: { done: 1, total: 2, estimate: 20000, actual: 8400 } });
    const kids = [
      card({ id: "K1", parent: "WF-086", status: "done", updated: "2026-08-10" }),
      card({ id: "K2", parent: "WF-086", status: "planned", complexity: "L" }),
    ];
    const onToggle = vi.fn();
    const { rerender } = renderEpic(
      <EpicCard card={epic} childCards={kids} expanded={false} onToggleExpand={onToggle} />
    );
    expect(screen.getByText("1 / 2 quests")).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /sub-quests/i });
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalledWith("WF-086");
    // collapsed → rows absent
    expect(screen.queryByText("K2")).toBeNull();
    // expanded → rows present, done row struck (has --done class), todo shows weight
    rerender(<EpicCard card={epic} childCards={kids} expanded={true} onToggleExpand={onToggle} />);
    expect(screen.getByText("K2")).toBeInTheDocument();
  });

  it("shows no expand toggle when the epic has no children", () => {
    const epic = card({ id: "WF-0", is_epic: true, rollup: { done: 0, total: 0, estimate: null, actual: 0 } });
    renderEpic(<EpicCard card={epic} childCards={[]} expanded={false} onToggleExpand={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /sub-quests/i })).toBeNull();
  });
});
