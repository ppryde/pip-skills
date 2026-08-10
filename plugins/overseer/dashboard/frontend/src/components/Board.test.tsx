import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BoardCard, BoardResponse, CardDetail } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test. getSessions
// is required even though this file doesn't exercise Party behaviour — a
// full <App/> render now mounts useSessions() unconditionally (WF-029), and
// an unmocked import throws "getSessions is not a function".
vi.mock("../api/client", () => ({
  getBoard: vi.fn(),
  getCard: vi.fn(),
  getSessions: vi.fn(),
  getRepos: vi.fn(),
  setActiveRoot: vi.fn(),
}));

import { getBoard, getCard, getSessions, getRepos } from "../api/client";
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
    label_colors: {},
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
      // A card waiting on a dependency, with an in-progress checklist.
      card({
        id: "WF-WAITING",
        title: "Blocked on the epic",
        ready: false,
        depends_on: ["WF-EPIC"],
        checklist: [
          { task: "1", subject: "Write the design doc", status: "completed" },
          { task: "2", subject: "Implement the thing", status: "in_progress" },
          { task: "3", subject: "Ship it", status: "pending" },
        ],
      }),
      // A parked card whose budget has blown the 2x tripwire.
      card({
        id: "WF-OVERBUDGET",
        title: "Way over budget",
        status: "parked",
        budget: { estimate: 5, actual: 12 },
      }),
      // A DONE card with no relation to WF-EPIC — used to prove the
      // epic-focus dim reaches the Done lane the same as every other lane
      // (regression coverage for the `.card-tile--done` opacity clobber).
      card({
        id: "WF-SHIPPED",
        title: "Already shipped",
        status: "done",
      }),
    ],
  },
  context: { pct: 42, threshold: 80 },
  limits: null,
};

describe("<App/> board render (read-only, Chunk 3)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // Default: no active sessions, no discoverable repos. resetAllMocks()
    // clears implementations too, so these are re-armed before every test
    // in this describe block.
    vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
    vi.mocked(getRepos).mockResolvedValue({ repos: [] });
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

  it("(WF-085) the card count no longer renders in the lane header — it lives only in the icon-nav", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);

    const { container } = render(<App />);
    await screen.findByText("Backlog");

    // `.lane__count` is gone from every lane header, on every viewport
    // (the count-removal isn't gated to mobile).
    expect(container.querySelector(".lane__count")).not.toBeInTheDocument();

    // ...but the same counts now surface in the mobile icon-nav (always
    // rendered in the DOM — CSS is what hides the strip above 720px).
    // Backlog: WF-EPIC + WF-WAITING. Implementation: WF-EPIC-C2. Parked:
    // WF-OVERBUDGET. Done: WF-EPIC-C1 + WF-SHIPPED.
    expect(screen.getByLabelText("Backlog, 2 cards")).toBeInTheDocument();
    expect(screen.getByLabelText("Implementation, 1 cards")).toBeInTheDocument();
    expect(screen.getByLabelText("Parked, 1 cards")).toBeInTheDocument();
    expect(screen.getByLabelText("Done, 2 cards")).toBeInTheDocument();
    // An empty stage lane does NOT get a nav icon — the nav strip only
    // lists non-empty lanes (WF-085a review). The swipe track still renders
    // the empty lane as a thin strip; only the nav filters it out, since an
    // empty lane isn't a swipe snap-stop (`.lane--empty { scroll-snap-align:
    // none }`) and a tap-to-jump there would land on a non-snap target.
    expect(screen.queryByLabelText("Bootstrap, 0 cards")).not.toBeInTheDocument();
  });

  it("(WF-085) tapping an icon-nav entry marks it active and jumps the matching lane pane into view", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(fixture);
    // jsdom doesn't implement scrollIntoView at all — polyfill it so
    // Board's guarded call has something to invoke and assert on.
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    render(<App />);
    await screen.findByText("Backlog");

    const doneIcon = screen.getByLabelText("Done, 2 cards");
    expect(doneIcon).not.toHaveClass("lane-icon-nav__item--active");

    fireEvent.click(doneIcon);

    expect(doneIcon).toHaveClass("lane-icon-nav__item--active");
    expect(scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ inline: "center" })
    );
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

    // An unrelated DONE card must dim exactly like every other lane's cards
    // do — the Done lane's filled/opaque treatment must not swallow the
    // epic-focus dim.
    expect(
      container.querySelector('[data-card-id="WF-SHIPPED"]')
    ).toHaveClass("card-tile--dimmed");
    expect(
      container.querySelector('[data-card-id="WF-SHIPPED"]')
    ).not.toHaveClass("card-tile--highlighted");

    // ...but the drawer stayed shut (expand is a distinct action from open).
    expect(getCard).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("(checklist) a tile with tasks shows the windowed subjects, and clicking a row still opens the drawer", async () => {
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

    // Windowed subjects render on the tile itself.
    expect(screen.getByText("Write the design doc")).toBeInTheDocument();
    expect(screen.getByText("Implement the thing")).toBeInTheDocument();
    expect(screen.getByText("Ship it")).toBeInTheDocument();

    // The checklist is inert — clicking a row is just a click inside the
    // tile body, which still opens the drawer via the body's onOpen.
    fireEvent.click(screen.getByText("Implement the thing"));

    expect(getCard).toHaveBeenCalledWith("WF-WAITING");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    // And the no-nested-interactive invariant still holds board-wide.
    const interactives = container.querySelectorAll(
      'button, [role="button"], a[href]'
    );
    expect(interactives.length).toBeGreaterThan(0);
    interactives.forEach((el) => {
      expect(el.querySelector('button, [role="button"], a[href]')).toBeNull();
    });
  });
});

describe("<App/> branch filter — dim + spotlight (WF-031)", () => {
  const branchFixture: BoardResponse = {
    board: {
      project: "overseer-dashboard",
      sprints: [],
      quarantined: [],
      label_colors: {},
      cards: [
        card({ id: "WF-A", title: "On branch a", branch: "feat/a" }),
        card({ id: "WF-B", title: "On branch b", branch: "feat/b" }),
        card({ id: "WF-C", title: "No branch at all" }),
        // A DONE card on a different branch — regression coverage for the
        // `.card-tile--done` opacity clobber on the branch-filter `is-dimmed`
        // side (mirrors the epic-focus WF-SHIPPED case above).
        card({ id: "WF-D", title: "Shipped on branch b", branch: "feat/b", status: "done" }),
      ],
    },
    context: { pct: 10, threshold: 80 },
    limits: null,
  };

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getRepos).mockResolvedValue({ repos: [] });
  });

  it("selecting a branch dims non-matching cards and spotlights the matching one, leaving branchless cards neutral (task 10)", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(branchFixture);
    vi.mocked(getSessions).mockResolvedValue({ sessions: [] });

    const { container } = render(<App />);
    await screen.findByText("On branch a");

    fireEvent.change(screen.getByLabelText("Branch"), {
      target: { value: "feat/a" },
    });

    expect(
      container.querySelector('[data-card-id="WF-A"]')
    ).toHaveClass("is-spotlight");
    expect(
      container.querySelector('[data-card-id="WF-A"]')
    ).not.toHaveClass("is-dimmed");
    // WF-B is ON a different branch — dimmed.
    expect(
      container.querySelector('[data-card-id="WF-B"]')
    ).toHaveClass("is-dimmed");
    // WF-C has NO branch at all (unclaimed backlog) — stays neutral, never
    // dimmed alongside cards that are actively on another branch.
    expect(
      container.querySelector('[data-card-id="WF-C"]')
    ).not.toHaveClass("is-dimmed");
    expect(
      container.querySelector('[data-card-id="WF-C"]')
    ).not.toHaveClass("is-spotlight");
    // A DONE card on a different branch must dim exactly like any other
    // lane's card — the Done lane's own opacity must not swallow it.
    expect(
      container.querySelector('[data-card-id="WF-D"]')
    ).toHaveClass("is-dimmed");
    expect(
      container.querySelector('[data-card-id="WF-D"]')
    ).toHaveClass("card-tile--done");
  });

  it("selecting a branch spotlights the Party agent on it", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(branchFixture);
    vi.mocked(getSessions).mockResolvedValue({
      sessions: [
        { id: "s1", worktree_cwd: "/w/a", updated_at: 1, stale: false, branch: "feat/a" },
        { id: "s2", worktree_cwd: "/w/b", updated_at: 1, stale: false, branch: "feat/b" },
      ],
    });

    const { container } = render(<App />);
    await screen.findByText("On branch a");
    await waitFor(() => {
      expect(container.querySelectorAll(".party-row__branch").length).toBe(2);
    });

    fireEvent.change(screen.getByLabelText("Branch"), {
      target: { value: "feat/a" },
    });

    const rows = container.querySelectorAll(".party-row");
    const rowForA = Array.from(rows).find((r) =>
      r.textContent?.includes("feat/a")
    );
    const rowForB = Array.from(rows).find((r) =>
      r.textContent?.includes("feat/b")
    );
    expect(rowForA).toHaveClass("is-spotlight");
    expect(rowForB).not.toHaveClass("is-spotlight");
  });

  it("choosing 'All' clears every dim/spotlight", async () => {
    vi.mocked(getBoard).mockResolvedValueOnce(branchFixture);
    vi.mocked(getSessions).mockResolvedValue({ sessions: [] });

    const { container } = render(<App />);
    await screen.findByText("On branch a");

    const select = screen.getByLabelText("Branch");
    fireEvent.change(select, { target: { value: "feat/a" } });
    expect(container.querySelector(".is-dimmed")).not.toBeNull();

    fireEvent.change(select, { target: { value: "" } });

    expect(container.querySelector(".is-dimmed")).toBeNull();
    expect(container.querySelector(".is-spotlight")).toBeNull();
  });
});

// WF-085 review (both final reviewers, CONFIRMED): at <=720px `.board` (not
// `.board-region`) is the intended horizontal scroller — Board.tsx binds
// onScroll={handleTrackScroll} directly to the `.board` div, and LaneIconNav
// is a sibling of `.board` inside `.board-region` that must stay put while
// `.board` scrolls. Two bugs conspired to break this: (1) the base
// `.board { min-width: max-content }` rule was never overridden on mobile,
// so `.board` had no internal overflow of its own — it overflowed its
// PARENT `.board-region` instead, making `.board-region` the real
// horizontal scroller and dragging the icon-nav off-screen on swipe; (2) a
// duplicate/orphaned `.board-region` rule (resurrected by cherry-pick
// 470fd6d) still declared `scroll-snap-type: x mandatory` inside the mobile
// media query, alongside the later intentional `.board-region` rule — a
// second, competing horizontal snap container nested around `.board`.
// styles.css is never imported by these component tests (only main.tsx
// imports it, and CSS imports are stubbed under vitest — see the
// WF-082/WF-085b guards in CardDetailDrawer.test.tsx/TopBar.test.tsx for the
// same rationale), so this reads the real stylesheet source directly.
describe("mobile board scroll-container (WF-085 review — CSS regression guard)", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "styles.css"),
    "utf8"
  );

  // Isolate the `@media (max-width: 720px) { ... }` block by brace-depth
  // matching (the block contains many nested rules, so a naive
  // non-greedy `[^}]*` regex would stop at the first inner `}`).
  function mobileBlock(): string {
    const start = css.indexOf("@media (max-width: 720px)");
    expect(
      start,
      "expected an @media (max-width: 720px) block in styles.css"
    ).toBeGreaterThan(-1);
    const braceStart = css.indexOf("{", start);
    let depth = 0;
    let i = braceStart;
    for (; i < css.length; i++) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") {
        depth--;
        if (depth === 0) break;
      }
    }
    return css.slice(braceStart + 1, i);
  }

  function ruleBodies(block: string, selector: string): string[] {
    const escaped = selector.replace(/[.]/g, "\\.");
    const re = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "g");
    const bodies: string[] = [];
    let match: RegExpExecArray | null;
    while ((match = re.exec(block))) {
      bodies.push(match[1]);
    }
    return bodies;
  }

  it("no mobile .board-region rule declares scroll-snap-type (the orphaned duplicate from 470fd6d is gone)", () => {
    const bodies = ruleBodies(mobileBlock(), ".board-region");
    expect(
      bodies.length,
      "expected at least one .board-region rule inside the mobile block"
    ).toBeGreaterThan(0);
    for (const body of bodies) {
      expect(body).not.toMatch(/scroll-snap-type/);
    }
  });

  it("the mobile .board rule overrides min-width to 0, so .board (not .board-region) has real internal overflow", () => {
    // `\.board\s*\{` (not `.board-region`/`.board-toast`/etc — those have
    // a `-` immediately after "board", not whitespace then "{").
    const bodies = ruleBodies(mobileBlock(), ".board");
    expect(
      bodies.length,
      "expected an exact `.board { ... }` rule inside the mobile block"
    ).toBeGreaterThan(0);
    expect(bodies.some((body) => /min-width:\s*0\b/.test(body))).toBe(true);
  });
});
