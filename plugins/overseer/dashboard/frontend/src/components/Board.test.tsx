import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { BoardCard, BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  getBoard: vi.fn(),
}));

import { getBoard } from "../api/client";
import App from "../App";

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

const fixture: BoardResponse = {
  board: {
    project: "overseer-dashboard",
    sprints: [],
    quarantined: ["WF-BAD"],
    cards: [
      // Epic in Backlog (planned) with two children in other lanes.
      card({
        id: "WF-EPIC",
        title: "Ship the dashboard",
        is_epic: true,
        status: "planned",
        rollup: { done: 1, total: 2, estimate: 20, actual: 10 },
      }),
      card({
        id: "WF-EPIC-C1",
        title: "Epic child (done)",
        parent: "WF-EPIC",
        status: "done",
      }),
      card({
        id: "WF-EPIC-C2",
        title: "Epic child (in flight)",
        parent: "WF-EPIC",
        status: "in-flight",
        stage: "implementation",
      }),
      // A card waiting on a dependency.
      card({
        id: "WF-WAITING",
        title: "Blocked on the epic",
        ready: false,
        depends_on: ["WF-EPIC"],
      }),
      // A parked card whose budget has blown the 2x tripwire.
      card({
        id: "WF-OVERBUDGET",
        title: "Way over budget",
        status: "parked",
        budget: { estimate: 5, actual: 12 },
      }),
    ],
  },
  context: { pct: 42, threshold: 80 },
  limits: null,
};

describe("<App/> board render (read-only, Chunk 3)", () => {
  it("renders lanes, an epic rollup line, a waiting-on dependency badge, and a tripwire flag", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);

    render(<App />);

    // Lanes are present (labels from layout.ts).
    expect(await screen.findByText("Backlog")).toBeInTheDocument();
    expect(screen.getByText("Implementation")).toBeInTheDocument();
    expect(screen.getByText("Parked")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();

    // Every card rendered exactly once — no epic-child duplication/hiding.
    expect(screen.getByText("Ship the dashboard")).toBeInTheDocument();
    expect(screen.getByText("Epic child (done)")).toBeInTheDocument();
    expect(screen.getByText("Epic child (in flight)")).toBeInTheDocument();

    // Epic rollup line.
    expect(screen.getByText(/1\/2 done/)).toBeInTheDocument();

    // Dependency "waiting on" badge.
    expect(screen.getByText(/waiting on WF-EPIC/)).toBeInTheDocument();

    // Budget tripwire flag.
    expect(screen.getByTitle("Actual is at least 2x the estimate")).toBeInTheDocument();

    // Quarantined banner from board.quarantined.
    expect(screen.getByText(/1 quarantined/)).toBeInTheDocument();
  });
});
