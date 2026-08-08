import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import type { BoardResponse, SessionsResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  getSessions: vi.fn(),
  claimCard: vi.fn(),
  unclaimCard: vi.fn(),
}));

import { claimCard, getSessions, unclaimCard } from "../api/client";
import ClaimControl from "./ClaimControl";

const BOARD_RESPONSE = {} as BoardResponse;

function sessionsResponse(
  sessions: SessionsResponse["sessions"]
): SessionsResponse {
  return { sessions };
}

/** Mimics `useBoard().mutate`: invokes `fn`, awaiting it. */
function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

describe("<ClaimControl/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders only LIVE sessions in the assign select", async () => {
    vi.mocked(getSessions).mockResolvedValue(
      sessionsResponse([
        { id: "s1", worktree_cwd: null, updated_at: null, stale: false, session_name: "night-shift" },
        { id: "s2", worktree_cwd: null, updated_at: null, stale: true, session_name: "ghost" },
      ])
    );
    const mutate = makeMutate();

    render(
      <ClaimControl cardId="WF-1" claimedBy={null} mutate={mutate} inFlight={false} />
    );

    const select = await screen.findByLabelText("Assign to session");
    await waitFor(() =>
      expect(within(select).getByText("night-shift")).toBeInTheDocument()
    );
    expect(within(select).queryByText("ghost")).not.toBeInTheDocument();
  });

  it("Assign calls claimCard(cardId, sessionId) via mutate", async () => {
    vi.mocked(getSessions).mockResolvedValue(
      sessionsResponse([
        { id: "s1", worktree_cwd: null, updated_at: null, stale: false, session_name: "night-shift" },
      ])
    );
    vi.mocked(claimCard).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    const onMutated = vi.fn();

    render(
      <ClaimControl
        cardId="WF-1"
        claimedBy={null}
        mutate={mutate}
        inFlight={false}
        onMutated={onMutated}
      />
    );

    const select = await screen.findByLabelText("Assign to session");
    fireEvent.change(select, { target: { value: "s1" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() => expect(claimCard).toHaveBeenCalledWith("WF-1", "s1"));
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(1));
  });

  it("the Assign button is disabled until a session is selected", async () => {
    vi.mocked(getSessions).mockResolvedValue(
      sessionsResponse([
        { id: "s1", worktree_cwd: null, updated_at: null, stale: false },
      ])
    );
    const mutate = makeMutate();

    render(
      <ClaimControl cardId="WF-1" claimedBy={null} mutate={mutate} inFlight={false} />
    );

    await screen.findByLabelText("Assign to session");
    expect(screen.getByRole("button", { name: "Assign" })).toBeDisabled();
  });

  it("shows the holder and an Unassign button when claimed", async () => {
    vi.mocked(getSessions).mockResolvedValue(
      sessionsResponse([
        { id: "s1", worktree_cwd: null, updated_at: null, stale: false, session_name: "night-shift" },
      ])
    );
    const mutate = makeMutate();

    render(
      <ClaimControl cardId="WF-1" claimedBy="s1" mutate={mutate} inFlight={false} />
    );

    expect(await screen.findByText(/claimed by night-shift/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unassign" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Assign to session")).not.toBeInTheDocument();
  });

  it("falls back to the raw session id when the holder isn't in the live sessions list", async () => {
    vi.mocked(getSessions).mockResolvedValue(sessionsResponse([]));
    const mutate = makeMutate();

    render(
      <ClaimControl
        cardId="WF-1"
        claimedBy="sess-unknown"
        mutate={mutate}
        inFlight={false}
      />
    );

    expect(
      await screen.findByText(/claimed by sess-unknown/)
    ).toBeInTheDocument();
  });

  it("dims the holder label when that session has gone stale", async () => {
    vi.mocked(getSessions).mockResolvedValue(
      sessionsResponse([
        { id: "s1", worktree_cwd: null, updated_at: null, stale: true, session_name: "ghost" },
      ])
    );
    const mutate = makeMutate();

    render(
      <ClaimControl cardId="WF-1" claimedBy="s1" mutate={mutate} inFlight={false} />
    );

    const holder = await screen.findByText(/claimed by ghost/);
    expect(holder).toHaveClass("claim-control__holder--stale");
  });

  it("Unassign calls unclaimCard(cardId) via mutate", async () => {
    vi.mocked(getSessions).mockResolvedValue(sessionsResponse([]));
    vi.mocked(unclaimCard).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    const onMutated = vi.fn();

    render(
      <ClaimControl
        cardId="WF-1"
        claimedBy="sess-1"
        mutate={mutate}
        inFlight={false}
        onMutated={onMutated}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "Unassign" }));

    await waitFor(() => expect(unclaimCard).toHaveBeenCalledWith("WF-1"));
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(1));
  });

  it("disables Assign/Unassign while a mutation is in flight", async () => {
    vi.mocked(getSessions).mockResolvedValue(sessionsResponse([]));
    const mutate = makeMutate();

    render(
      <ClaimControl cardId="WF-1" claimedBy="sess-1" mutate={mutate} inFlight={true} />
    );

    expect(await screen.findByRole("button", { name: "Unassign" })).toBeDisabled();
  });
});
