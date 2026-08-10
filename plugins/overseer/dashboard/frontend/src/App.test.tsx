import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { BoardCard, BoardResponse, RepoEntry } from "./api/types";

// Only the read endpoints App's mount path touches are stubbed — every
// other export is the real module (mutations are never exercised by this
// suite, and re-exporting the real ones keeps the mock honest about the
// module's actual shape).
vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    getRepos: vi.fn(),
    getBoard: vi.fn(),
    getSessions: vi.fn(),
    setActiveRoot: vi.fn(),
  };
});

import * as client from "./api/client";
import App from "./App";

function repo(overrides: Partial<RepoEntry> & { label: string; root: string }): RepoEntry {
  return { current: false, has_board: true, live_sessions: 0, ...overrides };
}

function boardResponse(): BoardResponse {
  return {
    board: { project: "acme", cards: [], sprints: [], quarantined: [] },
    context: { pct: 10, threshold: 80 },
    limits: null,
  };
}

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
    ...overrides,
  };
}

describe("<App/> — WF-032 unbegun-repo holding page wiring", () => {
  beforeEach(() => {
    vi.mocked(client.getSessions).mockResolvedValue({ sessions: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("selecting a has_board:true repo still fetches and shows the board", async () => {
    vi.mocked(client.getRepos).mockResolvedValue({
      repos: [repo({ label: "acme", root: "/acme", current: true, has_board: true })],
    });
    vi.mocked(client.getBoard).mockResolvedValue(boardResponse());

    render(<App />);

    // Wait for the repos fetch to resolve and populate the selector before
    // asserting on the board fetch — the board's own mount fetch can fire
    // (and even resolve) before `/api/repos` does.
    await waitFor(() => expect(screen.getByLabelText("Repo")).toBeInTheDocument());
    await waitFor(() => expect(client.getBoard).toHaveBeenCalled());
    expect(
      screen.queryByText(/quest has not yet begun/i)
    ).not.toBeInTheDocument();
  });

  it("selecting an unbegun repo renders the holding page with its name and pluralised agent count, and never calls getBoard for it", async () => {
    vi.mocked(client.getRepos).mockResolvedValue({
      repos: [
        repo({ label: "acme", root: "/acme", current: true, has_board: true }),
        repo({
          label: "sandbox",
          root: "/sandbox",
          has_board: false,
          live_sessions: 6,
        }),
      ],
    });
    vi.mocked(client.getBoard).mockResolvedValue(boardResponse());

    render(<App />);

    // Let the default (has_board:true) repo's board load first, same as the
    // "still shows the board" case above.
    await waitFor(() => expect(screen.getByLabelText("Repo")).toBeInTheDocument());
    await waitFor(() => expect(client.getBoard).toHaveBeenCalled());
    const callsBeforeSwitch = vi.mocked(client.getBoard).mock.calls.length;
    const sessionCallsBeforeSwitch = vi.mocked(client.getSessions).mock.calls.length;

    fireEvent.change(screen.getByLabelText("Repo"), {
      target: { value: "/sandbox" },
    });

    await waitFor(() =>
      expect(screen.getByText(/quest has not yet begun/i)).toBeInTheDocument()
    );

    // Repo name + pluralised ("6 adventurers") count in the holding copy.
    expect(screen.getByText("sandbox")).toBeInTheDocument();
    expect(screen.getByText(/6 adventurers already roam/i)).toBeInTheDocument();

    // The board fetch must NEVER have fired again for the unbegun repo —
    // an unbegun root 400s /api/board on the backend.
    expect(vi.mocked(client.getBoard).mock.calls.length).toBe(callsBeforeSwitch);

    // Task 10: `useSessions` is now gated off (`enabled: !isUnbegun`) exactly
    // like `useBoard` — an unbegun root 400s `/api/sessions` too, so no new
    // call fires for it, and `setActiveRoot` isn't re-scoped to it either.
    expect(vi.mocked(client.getSessions).mock.calls.length).toBe(
      sessionCallsBeforeSwitch
    );
    expect(client.setActiveRoot).not.toHaveBeenCalledWith("/sandbox");

    // The questing pill must not show a contradictory "0 questing" next to
    // the holding page's own "6 adventurers already roam these lands" — it
    // sources its count from the same `live_sessions` figure instead.
    expect(screen.getByText("6 questing")).toBeInTheDocument();
  });

  it("WF-045: clicking the fleet pill on an unbegun repo does not open the Party overlay with the PREVIOUS repo's stale heroes", async () => {
    vi.mocked(client.getRepos).mockResolvedValue({
      repos: [
        repo({ label: "acme", root: "/acme", current: true, has_board: true }),
        repo({
          label: "sandbox",
          root: "/sandbox",
          has_board: false,
          live_sessions: 6,
        }),
      ],
    });
    vi.mocked(client.getBoard).mockResolvedValue(boardResponse());
    // acme has one live census session — this is the "previous repo's hero"
    // that must never leak into the Party overlay once we've switched to an
    // unbegun repo.
    vi.mocked(client.getSessions).mockResolvedValue({
      sessions: [
        {
          id: "sess-stale-hero",
          worktree_cwd: "/acme",
          updated_at: 100,
          stale: false,
          session_name: "Sir Stale-a-lot",
        },
      ],
    });

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("Repo")).toBeInTheDocument());
    await waitFor(() => expect(client.getBoard).toHaveBeenCalled());
    // Confirm the party actually populated from acme's session before we
    // switch repos — otherwise the "no leak" assertion below would be
    // vacuously true.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /1 questing/ })).toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText("Repo"), {
      target: { value: "/sandbox" },
    });
    await waitFor(() =>
      expect(screen.getByText(/quest has not yet begun/i)).toBeInTheDocument()
    );

    fireEvent.click(screen.getByRole("button", { name: /questing/ }));

    expect(screen.queryByTestId("party-overlay")).not.toBeInTheDocument();
    expect(screen.queryByText("Sir Stale-a-lot")).not.toBeInTheDocument();
  });
});

describe("<App/> — task 7: Clear control wiring", () => {
  beforeEach(() => {
    vi.mocked(client.getSessions).mockResolvedValue({ sessions: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows a Clear button once a repo is selected, and clicking it opens ClearDialog scoped to that repo", async () => {
    vi.mocked(client.getRepos).mockResolvedValue({
      repos: [repo({ label: "acme", root: "/acme", current: true, has_board: true })],
    });
    vi.mocked(client.getBoard).mockResolvedValue(boardResponse());

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("Repo")).toBeInTheDocument());
    await waitFor(() => expect(client.getBoard).toHaveBeenCalled());

    // Exact "Clear…" (with ellipsis) — task 6 added a second, unrelated
    // "Clear filters" button to the filter bar, so a bare /clear/i now
    // matches both.
    const clearButton = await screen.findByRole("button", { name: "Clear…" });
    fireEvent.click(clearButton);

    const dialog = await screen.findByRole("dialog", {
      name: /clear repository data/i,
    });
    expect(dialog).toBeInTheDocument();
    // Scoped to the SELECTED repo's label, per App.tsx's
    // `selectedRepo.label`/`selectedRepo.root` props to `<ClearDialog/>`.
    expect(dialog.textContent).toMatch(/acme/);
  });

  it("renders no Clear button before any repo is selected", async () => {
    vi.mocked(client.getRepos).mockResolvedValue({ repos: [] });
    vi.mocked(client.getBoard).mockResolvedValue(boardResponse());

    render(<App />);

    await waitFor(() => expect(client.getRepos).toHaveBeenCalled());
    // Exact "Clear…" — see the sibling test above for why a bare /clear/i
    // regex is no longer specific enough post-task-6 (filter bar's own
    // "Clear filters" button renders here regardless of repo selection).
    expect(
      screen.queryByRole("button", { name: "Clear…" })
    ).not.toBeInTheDocument();
  });
});

describe("<App/> — task 6: filter bar wiring (WF-059/060/061)", () => {
  beforeEach(() => {
    vi.mocked(client.getSessions).mockResolvedValue({ sessions: [] });
    vi.mocked(client.getRepos).mockResolvedValue({
      repos: [repo({ label: "acme", root: "/acme", current: true, has_board: true })],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("searching an epic's title reveals its children and hides unrelated cards", async () => {
    vi.mocked(client.getBoard).mockResolvedValue({
      board: {
        project: "acme",
        sprints: [],
        quarantined: [],
        cards: [
          card({ id: "WF-EPIC", title: "The great migration", is_epic: true }),
          card({ id: "WF-EPIC-C1", title: "Migration child", parent: "WF-EPIC" }),
          card({ id: "WF-OTHER", title: "Totally unrelated card" }),
        ],
      },
      context: { pct: 10, threshold: 80 },
      limits: null,
    });

    render(<App />);

    await waitFor(() => expect(client.getBoard).toHaveBeenCalled());
    expect(await screen.findByText("Totally unrelated card")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("search"), {
      target: { value: "migration" },
    });

    await waitFor(() =>
      expect(screen.queryByText("Totally unrelated card")).not.toBeInTheDocument()
    );
    expect(screen.getByText("The great migration")).toBeInTheDocument();
    expect(screen.getByText("Migration child")).toBeInTheDocument();
  });
});
