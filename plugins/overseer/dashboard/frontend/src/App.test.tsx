import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { BoardResponse, RepoEntry } from "./api/types";

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
});
