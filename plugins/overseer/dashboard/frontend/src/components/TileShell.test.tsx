import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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

describe("TileShell tile-body opener (a11y: no nested interactive)", () => {
  function renderOpenable(
    opts: { onOpen?: (id: string) => void; headerExtra?: ReactNode } = {}
  ) {
    const c = card({ id: "WF-OPEN", title: "Open me" });
    return render(
      <DndContext>
        <SortableContext items={[c.id]}>
          <TileShell
            card={c}
            onOpen={opts.onOpen}
            headerExtra={opts.headerExtra}
          />
        </SortableContext>
      </DndContext>
    );
  }

  it("exposes the tile title as a real, focusable button (keyboard-reachable open)", () => {
    const onOpen = vi.fn();
    renderOpenable({ onOpen });

    // The open affordance is a genuine <button> — not a role=button div that
    // relied on a manual tabIndex/onKeyDown handler — so it is natively
    // keyboard-reachable and screen-reader-announced as one control.
    const opener = screen.getByRole("button", { name: "Open me" });
    opener.focus();
    expect(opener).toHaveFocus();

    fireEvent.click(opener);
    expect(onOpen).toHaveBeenCalledWith("WF-OPEN");
    // Single fire — the opener stops the click from also reaching the body.
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("the tile body container is NOT itself an interactive role", () => {
    const { container } = renderOpenable({ onOpen: vi.fn() });
    const body = container.querySelector(".card-tile__body");
    expect(body).not.toBeNull();
    expect(body!.getAttribute("role")).toBeNull();
    expect(body!.getAttribute("tabindex")).toBeNull();
  });

  it("nests NO interactive element inside another (handle, opener, headerExtra)", () => {
    const headerExtra = (
      <button type="button" onClick={(e) => e.stopPropagation()}>
        expand
      </button>
    );
    const { container } = renderOpenable({ onOpen: vi.fn(), headerExtra });

    const interactives = container.querySelectorAll(
      'button, [role="button"], a[href]'
    );
    expect(interactives.length).toBeGreaterThan(0);
    interactives.forEach((el) => {
      expect(el.querySelector('button, [role="button"], a[href]')).toBeNull();
    });
  });

  it("a headerExtra button that stops propagation does NOT trigger open", () => {
    const onOpen = vi.fn();
    const onExtra = vi.fn();
    const headerExtra = (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onExtra();
        }}
      >
        expand
      </button>
    );
    renderOpenable({ onOpen, headerExtra });

    fireEvent.click(screen.getByRole("button", { name: "expand" }));
    expect(onExtra).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("clicking the body (outside the opener/headerExtra) opens via mouse", () => {
    const onOpen = vi.fn();
    const { container } = renderOpenable({ onOpen });
    const body = container.querySelector<HTMLElement>(".card-tile__body")!;
    fireEvent.click(body);
    expect(onOpen).toHaveBeenCalledWith("WF-OPEN");
  });
});
