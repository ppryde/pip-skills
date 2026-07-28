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
    checklist: [],
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

describe("TileShell repo chip", () => {
  it("renders the repo chip when the card carries a repo label", () => {
    const { container } = renderTile(
      card({ id: "WF-REPO", repo: "pip-skills" })
    );
    const chip = container.querySelector(".repo-chip");
    expect(chip).not.toBeNull();
    expect(chip).toHaveTextContent("pip-skills");
  });

  it("renders no repo chip when the card carries no repo label", () => {
    const { container } = renderTile(card({ id: "WF-NOREPO" }));
    expect(container.querySelector(".repo-chip")).toBeNull();
  });
});

describe("TileShell claim badge", () => {
  it("renders the claim badge when the card is claimed", () => {
    const { container } = renderTile(
      card({ id: "WF-CLAIMED", claimed_by: "sess-1" })
    );
    const badge = container.querySelector(".claim-badge");
    expect(badge).not.toBeNull();
    expect(badge).toHaveAttribute("title", "sess-1");
  });

  it("renders no claim badge when the card carries no claimed_by", () => {
    const { container } = renderTile(card({ id: "WF-UNCLAIMED" }));
    expect(container.querySelector(".claim-badge")).toBeNull();
  });
});

describe("TileShell checklist focus window", () => {
  function renderTileWith(checklist: BoardCard["checklist"]) {
    const c = card({ id: "WF-CHK", title: "Has tasks", checklist });
    return render(
      <DndContext>
        <SortableContext items={[c.id]}>
          <TileShell card={c} />
        </SortableContext>
      </DndContext>
    );
  }

  it("renders nothing (no reserved space) when the checklist is empty", () => {
    const { container } = renderTileWith([]);
    expect(container.querySelector(".checklist")).toBeNull();
  });

  it("renders the windowed subjects for a non-empty checklist", () => {
    renderTileWith([
      { task: "1", subject: "Write tests", status: "completed" },
      { task: "2", subject: "Implement", status: "in_progress" },
      { task: "3", subject: "Wire up", status: "pending" },
    ]);
    expect(screen.getByText("Write tests")).toBeInTheDocument();
    expect(screen.getByText("Implement")).toBeInTheDocument();
    expect(screen.getByText("Wire up")).toBeInTheDocument();
  });

  it("caps a long checklist to the 3-row sliding-wheel window", () => {
    const checklist = Array.from({ length: 8 }, (_, i) => ({
      task: String(i + 1),
      subject: `Task ${i + 1}`,
      status: i === 0 ? "in_progress" : "completed",
    }));
    const { container } = renderTileWith(checklist);
    expect(container.querySelectorAll(".checklist__row").length).toBe(3);
  });

  it("marks the active row and fades its neighbours by distance", () => {
    const checklist = Array.from({ length: 8 }, (_, i) => ({
      task: String(i + 1),
      subject: `Task ${i + 1}`,
      status: i === 3 ? "in_progress" : "completed",
    }));
    const { container } = renderTileWith(checklist);
    const rows = Array.from(container.querySelectorAll(".checklist__row"));
    expect(rows.map((r) => r.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("Task 4")])
    );
    const active = rows.find((r) => r.textContent?.includes("Task 4"));
    expect(active).toHaveClass("checklist__row--active");
    rows
      .filter((r) => r !== active)
      .forEach((r) => {
        expect(r.className).toMatch(/checklist__row--dist-[12]/);
      });
  });

  it("renders the checklist as inert content — no interactive element inside it", () => {
    const { container } = renderTileWith([
      { task: "1", subject: "Write tests", status: "in_progress" },
    ]);
    const list = container.querySelector(".checklist")!;
    expect(list).not.toBeNull();
    expect(
      list.querySelectorAll('button, a, [role="button"]').length
    ).toBe(0);
  });

  it("the checklist rows do NOT nest inside any interactive element (no-nested-interactive invariant)", () => {
    const { container } = renderTileWith([
      { task: "1", subject: "Write tests", status: "in_progress" },
    ]);
    const interactives = container.querySelectorAll(
      'button, [role="button"], a[href]'
    );
    expect(interactives.length).toBeGreaterThan(0);
    interactives.forEach((el) => {
      expect(el.querySelector('button, [role="button"], a[href]')).toBeNull();
    });
  });

  it("clicking a checklist row still opens the drawer — it's inert content inside the body", () => {
    const onOpen = vi.fn();
    const c = card({
      id: "WF-CHK-OPEN",
      title: "Has tasks",
      checklist: [{ task: "1", subject: "Write tests", status: "in_progress" }],
    });
    render(
      <DndContext>
        <SortableContext items={[c.id]}>
          <TileShell card={c} onOpen={onOpen} />
        </SortableContext>
      </DndContext>
    );
    fireEvent.click(screen.getByText("Write tests"));
    expect(onOpen).toHaveBeenCalledWith("WF-CHK-OPEN");
  });

  it("windowed mode applies the edge-fade container class", () => {
    const { container } = renderTileWith([
      { task: "1", subject: "Write tests", status: "in_progress" },
    ]);
    expect(container.querySelector(".checklist")).toHaveClass(
      "checklist--windowed"
    );
  });
});

describe("TileShell in-flight progress bar (WF-028 chunk 5)", () => {
  function renderInFlight(checklist: BoardCard["checklist"]) {
    const c = card({
      id: "WF-PROG",
      title: "In flight",
      status: "in-flight",
      stage: "implementation",
      checklist,
    });
    return render(
      <DndContext>
        <SortableContext items={[c.id]}>
          <TileShell card={c} />
        </SortableContext>
      </DndContext>
    );
  }

  it("renders no progress bar when the checklist is empty", () => {
    const { container } = renderInFlight([]);
    expect(container.querySelector(".card-tile__progress")).toBeNull();
  });

  it("renders no progress bar for a non-in-flight status even with a checklist", () => {
    const c = card({
      id: "WF-PROG-PLANNED",
      status: "planned",
      checklist: [{ task: "1", subject: "A", status: "pending" }],
    });
    const { container } = render(
      <DndContext>
        <SortableContext items={[c.id]}>
          <TileShell card={c} />
        </SortableContext>
      </DndContext>
    );
    expect(container.querySelector(".card-tile__progress")).toBeNull();
  });

  it("computes the percentage from the FULL checklist, not the windowed 3-row slice", () => {
    // 8 entries: 2 completed, 1 in_progress (the wheel's active row), 5
    // pending. The 3-row window centres on the active (in_progress) entry,
    // so its own done/total ratio (1/3 -> 33%) differs from the true
    // full-checklist ratio (2/8 -> 25%) — a same-shaped-array wrong-source
    // trap the two computations must NOT share.
    const checklist = Array.from({ length: 8 }, (_, i) => ({
      task: String(i + 1),
      subject: `Task ${i + 1}`,
      status: i < 2 ? "completed" : i === 2 ? "in_progress" : "pending",
    }));
    const { container } = renderInFlight(checklist);
    const bar = container.querySelector(".card-tile__progress");
    expect(bar).not.toBeNull();
    expect(bar).toHaveAttribute("data-progress-pct", "25");
  });

  it("shows 0% for an all-pending checklist and 100% for an all-completed one", () => {
    const { container: c0 } = renderInFlight([
      { task: "1", subject: "A", status: "pending" },
      { task: "2", subject: "B", status: "pending" },
    ]);
    expect(
      c0.querySelector(".card-tile__progress")
    ).toHaveAttribute("data-progress-pct", "0");

    const { container: c100 } = renderInFlight([
      { task: "1", subject: "A", status: "completed" },
      { task: "2", subject: "B", status: "completed" },
    ]);
    expect(
      c100.querySelector(".card-tile__progress")
    ).toHaveAttribute("data-progress-pct", "100");
  });
});
