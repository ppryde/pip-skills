import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { BoardCard, BoardResponse, CardDetail } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  getBoard: vi.fn(),
  getCard: vi.fn(),
}));

import { getBoard, getCard } from "../api/client";
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

function cardDetail(
  overrides: Partial<CardDetail> & { id: string }
): CardDetail {
  return {
    ...card(overrides),
    sections: {},
    body: "",
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
  beforeEach(() => {
    vi.resetAllMocks();
  });

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

  it("(Chunk 5) clicking a card BODY opens the drawer via the full App→Board→Lane→tile prop chain", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-WAITING",
        title: "Blocked on the epic",
        sections: { "## Goal": "Unblock the waiting card." },
      })
    );

    const { container } = render(<App />);
    await screen.findByText("Blocked on the epic");

    // Click the tile BODY (not the drag handle). The body carries the onOpen
    // wired all the way through the prop chain; a typo anywhere would break
    // this. Scope to WF-WAITING's tile so we click the right card's body.
    const body = container.querySelector<HTMLElement>(
      '[data-card-id="WF-WAITING"] .card-tile__body'
    );
    expect(body).not.toBeNull();
    fireEvent.click(body!);

    // The whole chain fired: getCard called with the clicked id, and the
    // drawer renders that card's fetched content.
    expect(getCard).toHaveBeenCalledWith("WF-WAITING");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(
      await screen.findByText("Unblock the waiting card.")
    ).toBeInTheDocument();
  });

  it("(Chunk 5) clicking the drag HANDLE does not open the drawer", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);

    const { container } = render(<App />);
    await screen.findByText("Blocked on the epic");

    const handle = container.querySelector<HTMLElement>(
      '[data-card-id="WF-WAITING"] .card-tile__handle'
    );
    expect(handle).not.toBeNull();
    fireEvent.click(handle!);

    // The handle is OUTSIDE the body — its click must not reach onOpen.
    expect(getCard).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("(a11y) no rendered tile nests an interactive control inside another", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);

    const { container } = render(<App />);
    // Wait for the epic (the tile that carries the nested expand button) to render.
    await screen.findByText("Ship the dashboard");

    const interactives = container.querySelectorAll(
      'button, [role="button"], a[href]'
    );
    expect(interactives.length).toBeGreaterThan(0);
    interactives.forEach((el) => {
      expect(el.querySelector('button, [role="button"], a[href]')).toBeNull();
    });
  });

  it("(a11y) the card title is a button that opens the drawer (keyboard path)", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-WAITING",
        title: "Blocked on the epic",
        sections: { "## Goal": "Unblock the waiting card." },
      })
    );

    render(<App />);
    await screen.findByText("Blocked on the epic");

    // The title is a real <button> (keyboard-activatable); activating it opens
    // the same drawer the body click does.
    const opener = screen.getByRole("button", { name: "Blocked on the epic" });
    fireEvent.click(opener);

    expect(getCard).toHaveBeenCalledWith("WF-WAITING");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("(a11y) the epic expand button toggles highlight WITHOUT opening the drawer", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);

    const { container } = render(<App />);
    await screen.findByText("Ship the dashboard");

    const expand = container.querySelector<HTMLElement>(
      '[data-card-id="WF-EPIC"] .epic-card__expand'
    );
    expect(expand).not.toBeNull();
    expect(expand!.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(expand!);

    // Toggled: aria-expanded flips and the epic tile becomes highlighted.
    expect(
      container
        .querySelector('[data-card-id="WF-EPIC"] .epic-card__expand')!
        .getAttribute("aria-expanded")
    ).toBe("true");
    expect(
      container.querySelector('[data-card-id="WF-EPIC"].card-tile--highlighted')
    ).not.toBeNull();

    // ...but the drawer stayed shut (expand is a distinct action from open).
    expect(getCard).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
