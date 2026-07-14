import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BoardResponse, CardDetail, SessionSummary } from "../api/types";
import type { PartyMember } from "../board/party";

// Mock the SOLE api client module — no real fetch in this test. Includes the
// mutation wrappers the wired-in controls (PrioritySelect/LinkEditor/
// StatusMenu) import, even though most tests here never trigger them.
vi.mock("../api/client", () => ({
  getCard: vi.fn(),
  setPriority: vi.fn(),
  setParent: vi.fn(),
  setDepends: vi.fn(),
  park: vi.fn(),
  unpark: vi.fn(),
  move: vi.fn(),
  getSessions: vi.fn(),
  claimCard: vi.fn(),
  unclaimCard: vi.fn(),
}));

import { getCard, getSessions, setPriority } from "../api/client";
import CardDetailDrawer from "./CardDetailDrawer";

const BOARD_RESPONSE = {} as BoardResponse;

/** No-op stub `mutate` for tests that never interact with a mutation
 * control — none of these render calls exercise a write. */
function noopMutate() {
  return vi.fn(async (_fn: () => Promise<BoardResponse>) => {});
}

/** Mimics `useBoard().mutate`: invokes `fn`, awaiting it — used by the
 * integration test below to verify the drawer refetches after a control's
 * mutation settles. */
function liveMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

function cardDetail(
  overrides: Partial<CardDetail> & { id: string }
): CardDetail {
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
    sections: {},
    body: "",
    ...overrides,
  };
}

function partyMember(
  overrides: Partial<SessionSummary> & { id: string }
): PartyMember {
  return {
    session: {
      worktree_cwd: "/w",
      updated_at: 1,
      stale: false,
      ...overrides,
    },
    questCardId: null,
    questTitle: null,
  };
}

/** A promise whose resolve/reject are exposed so tests drive ordering explicitly. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("<CardDetailDrawer/>", () => {
  // Each `it()` sets its own mockResolvedValueOnce/mockReturnValueOnce queue
  // and asserts on `getCard`'s call history (e.g. `toHaveBeenNthCalledWith`)
  // — reset fully between tests so one test's queued responses/call count
  // can't leak into the next.
  beforeEach(() => {
    vi.resetAllMocks();
    // ClaimControl (mounted whenever the drawer renders a card) fetches
    // sessions on mount — an empty list keeps it inert for tests that don't
    // exercise claim/assign behaviour themselves.
    vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
  });

  it("renders nothing when cardId is null", () => {
    render(
      <CardDetailDrawer
        cardId={null}
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(getCard).not.toHaveBeenCalled();
  });

  it("fetches the card lazily and renders its sections + header facts once resolved", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-A",
        title: "Do the thing",
        status: "in-flight",
        stage: "implementation",
        priority: "P1",
        sections: {
          "## Goal": "Ship the feature.",
          "## Plan": "Do steps 1, 2, 3.",
        },
      })
    );

    render(
      <CardDetailDrawer
        cardId="WF-A"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(getCard).toHaveBeenCalledWith("WF-A");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();

    expect(await screen.findByText("Do the thing")).toBeInTheDocument();
    expect(screen.getByText("Goal")).toBeInTheDocument();
    expect(screen.getByText("Ship the feature.")).toBeInTheDocument();
    expect(screen.getByText("Plan")).toBeInTheDocument();
    expect(screen.getByText("Do steps 1, 2, 3.")).toBeInTheDocument();
    expect(screen.getByText("P1")).toBeInTheDocument();
    expect(screen.getByText(/in-flight/)).toBeInTheDocument();
    expect(screen.getByText(/implementation/)).toBeInTheDocument();
  });

  it("renders the repo chip in the facts row when the card carries a repo label", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-A", repo: "pip-skills" })
    );

    render(
      <CardDetailDrawer
        cardId="WF-A"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(await screen.findByText("pip-skills")).toBeInTheDocument();
  });

  it("renders no repo chip when the card carries no repo label", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(cardDetail({ id: "WF-A" }));

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-A"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-A`);
    expect(container.querySelector(".repo-chip")).toBeNull();
  });

  it("renders unknown section headings too — no hardcoded fixed set", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-Z",
        sections: { "## Some New Heading": "Surprise content." },
      })
    );

    render(
      <CardDetailDrawer
        cardId="WF-Z"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(await screen.findByText("Some New Heading")).toBeInTheDocument();
    expect(screen.getByText("Surprise content.")).toBeInTheDocument();
  });

  it("falls back to raw body when sections is empty", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-B",
        sections: {},
        body: "Just some raw markdown body.",
      })
    );

    render(
      <CardDetailDrawer
        cardId="WF-B"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(
      await screen.findByText("Just some raw markdown body.")
    ).toBeInTheDocument();
  });

  it("shows an error state with the thrown detail message when the fetch rejects", async () => {
    vi.mocked(getCard).mockRejectedValueOnce(new Error("card not found"));

    render(
      <CardDetailDrawer
        cardId="WF-C"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(await screen.findByText("card not found")).toBeInTheDocument();
  });

  it("closes via Esc keydown, overlay click, and the close button", async () => {
    vi.mocked(getCard).mockResolvedValue(cardDetail({ id: "WF-D" }));
    const onClose = vi.fn();
    render(
      <CardDetailDrawer
        cardId="WF-D"
        onClose={onClose}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByRole("dialog");

    // Esc keydown.
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    // Overlay (backdrop) click — the outer `.drawer-overlay` div.
    await act(async () => {
      screen.getByTestId("drawer-overlay").click();
    });
    expect(onClose).toHaveBeenCalledTimes(2);

    // Close button.
    await act(async () => {
      screen.getByRole("button", { name: /close/i }).click();
    });
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("does NOT close when the click is inside the panel (stopPropagation on the inner aside)", async () => {
    vi.mocked(getCard).mockResolvedValue(
      cardDetail({ id: "WF-E", title: "Panel card" })
    );
    const onClose = vi.fn();
    render(
      <CardDetailDrawer
        cardId="WF-E"
        onClose={onClose}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText("Panel card");

    // Clicking the dialog panel itself must NOT bubble to the overlay handler.
    await act(async () => {
      screen.getByRole("dialog").click();
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("drops a stale getCard response: reopening a different card before the first resolves shows the LATER card's content, not the earlier one's", async () => {
    const first = deferred<CardDetail>();
    const second = deferred<CardDetail>();
    vi.mocked(getCard)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { rerender } = render(
      <CardDetailDrawer
        cardId="WF-A"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    expect(getCard).toHaveBeenNthCalledWith(1, "WF-A");

    // Reopen a DIFFERENT card before A's fetch resolves — B's request is now
    // the "latest issued".
    rerender(
      <CardDetailDrawer
        cardId="WF-B"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    expect(getCard).toHaveBeenNthCalledWith(2, "WF-B");

    // B resolves first, then the STALE A resolves after.
    await act(async () => {
      second.resolve(
        cardDetail({
          id: "WF-B",
          title: "Card B",
          sections: { "## Goal": "B goal" },
        })
      );
    });
    await screen.findByText("Card B");

    await act(async () => {
      first.resolve(
        cardDetail({
          id: "WF-A",
          title: "Card A",
          sections: { "## Goal": "A goal" },
        })
      );
    });

    // Still showing B — the late-arriving A response must be dropped.
    expect(screen.getByText("Card B")).toBeInTheDocument();
    expect(screen.queryByText("Card A")).not.toBeInTheDocument();
  });

  it("re-fetches the open card (getCard) after a drawer control's mutation settles", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-F", title: "Refetch me", priority: null })
    );
    vi.mocked(setPriority).mockResolvedValueOnce(BOARD_RESPONSE);
    // The refetch after the mutation returns updated content — proves it's
    // a REAL second `getCard` call, not just a re-render of stale state.
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-F", title: "Refetch me", priority: "P2" })
    );

    render(
      <CardDetailDrawer
        cardId="WF-F"
        onClose={() => {}}
        mutate={liveMutate()}
        inFlight={false}
        allCardIds={["WF-F"]}
        party={[]}
      />
    );
    await screen.findByText("Refetch me");
    expect(getCard).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.change(screen.getByLabelText("Priority"), {
        target: { value: "P2" },
      });
    });

    expect(setPriority).toHaveBeenCalledWith("WF-F", "P2");
    // The drawer's OWN getCard refetch fires as a SEPARATE concern from the
    // board refresh `mutate` performs — not just a re-render of the
    // mutation's board-response (which has no `sections`/`body` shape).
    await waitFor(() => expect(getCard).toHaveBeenCalledTimes(2));
  });

  it("guards a stale onMutated closure: no getCard fires when a control's mutation settles after the drawer has already closed", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-G", title: "Close me first", priority: null })
    );
    const setPriorityDeferred = deferred<BoardResponse>();
    vi.mocked(setPriority).mockReturnValueOnce(setPriorityDeferred.promise);

    const { rerender } = render(
      <CardDetailDrawer
        cardId="WF-G"
        onClose={() => {}}
        mutate={liveMutate()}
        inFlight={false}
        allCardIds={["WF-G"]}
        party={[]}
      />
    );
    await screen.findByText("Close me first");
    expect(getCard).toHaveBeenCalledTimes(1);

    // Kick off a mutation but don't let it settle yet.
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "P2" },
    });
    expect(setPriority).toHaveBeenCalledWith("WF-G", "P2");

    // Close the drawer BEFORE the in-flight mutation settles.
    rerender(
      <CardDetailDrawer
        cardId={null}
        onClose={() => {}}
        mutate={liveMutate()}
        inFlight={false}
        allCardIds={["WF-G"]}
        party={[]}
      />
    );

    // Now let the stale mutation resolve — its `onMutated` closure still
    // references the now-closed card.
    await act(async () => {
      setPriorityDeferred.resolve(BOARD_RESPONSE);
    });

    // No extra getCard call should have fired for the closed card.
    expect(getCard).toHaveBeenCalledTimes(1);
  });

  it("defaults to rendered view and toggles to verbatim source", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-H",
        title: "Toggle card",
        sections: { "## Goal": "Do the *thing*" },
        body: "# Goal\nDo the *thing*",
      })
    );

    render(
      <CardDetailDrawer
        cardId="WF-H"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText("Toggle card");

    expect(screen.getByRole("button", { name: /rendered/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByText("thing").tagName).toBe("EM"); // rendered markdown

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /source/i }));
    });

    const pre = screen.getByTestId("card-source");
    expect(pre.tagName).toBe("PRE");
    expect(pre).toHaveTextContent("# Goal"); // verbatim body incl. sigils
    expect(screen.queryByText("thing")?.tagName).not.toBe("EM");
  });

  it("resets to rendered when the drawer reopens", async () => {
    vi.mocked(getCard).mockResolvedValue(
      cardDetail({
        id: "WF-I",
        title: "Reopen card",
        sections: { "## Goal": "Do the *thing*" },
        body: "# Goal\nDo the *thing*",
      })
    );

    const { rerender } = render(
      <CardDetailDrawer
        cardId="WF-I"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText("Reopen card");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /source/i }));
    });
    expect(screen.getByRole("button", { name: /source/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    // Close the drawer.
    rerender(
      <CardDetailDrawer
        cardId={null}
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    // Reopen the SAME card.
    rerender(
      <CardDetailDrawer
        cardId="WF-I"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText("Reopen card");
    expect(screen.getByRole("button", { name: /rendered/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("renders a Tasks section with the FULL (unwindowed) checklist when non-empty", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-J",
        title: "Task card",
        checklist: [
          { task: "1", subject: "Write the design doc", status: "completed" },
          { task: "2", subject: "Implement", status: "in_progress" },
          { task: "3", subject: "Test", status: "pending" },
          { task: "4", subject: "Ship it", status: "pending" },
          { task: "5", subject: "Announce", status: "pending" },
          { task: "6", subject: "Clean up", status: "pending" },
        ],
      })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-J"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(await screen.findByText("Tasks")).toBeInTheDocument();
    // All six rows render — the drawer shows the full list, not the tile's
    // 5-row focus window.
    expect(screen.getByText("Write the design doc")).toBeInTheDocument();
    expect(screen.getByText("Clean up")).toBeInTheDocument();
    expect(container.querySelectorAll(".checklist__row").length).toBe(6);
    // Drawer mode is unwindowed — no edge-fade class.
    expect(container.querySelector(".checklist")).not.toHaveClass(
      "checklist--windowed"
    );
  });

  it("renders the assign-to-session control when the card is unclaimed", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-L", title: "Unclaimed", claimed_by: null })
    );

    render(
      <CardDetailDrawer
        cardId="WF-L"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(await screen.findByLabelText("Assign to session")).toBeInTheDocument();
  });

  it("renders the claim holder + Unassign button when the card is claimed", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-M", title: "Claimed", claimed_by: "sess-1" })
    );

    render(
      <CardDetailDrawer
        cardId="WF-M"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    expect(await screen.findByText(/claimed by sess-1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unassign" })).toBeInTheDocument();
  });

  it("renders no Tasks section when the checklist is empty", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-K", title: "No tasks", checklist: [] })
    );

    render(
      <CardDetailDrawer
        cardId="WF-K"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText("No tasks");
    expect(screen.queryByText("Tasks")).not.toBeInTheDocument();
  });

  it("renders the banner pill with the card's own stage label (WF-030 chunk 2)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-N", status: "in-flight", stage: "implementation" })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-N"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-N`);
    const banner = container.querySelector(".card-drawer__banner");
    expect(banner).toHaveTextContent("Implementation");
    expect(banner).toHaveClass("card-drawer__banner--implementation");
  });

  it("renders rarity stars when the card has a complexity", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-O", complexity: "M" })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-O"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-O`);
    expect(container.querySelectorAll(".card-drawer__star").length).toBe(3);
    expect(
      container.querySelectorAll(".card-drawer__star--filled").length
    ).toBe(2);
  });

  it("renders no stars row when the card has no complexity", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-P", complexity: null })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-P"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-P`);
    expect(container.querySelector(".card-drawer__stars")).toBeNull();
  });

  it("renders the hero chip WITH a PartyAvatar + class when the session is present in the shared party array", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-Q", claimed_by: "sess-1" })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-Q"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[
          partyMember({ id: "sess-1", session_name: "forge-master", model: "Opus" }),
        ]}
      />
    );

    await screen.findByText(`Title WF-Q`);
    const chip = container.querySelector(".card-drawer__hero-chip");
    expect(chip).not.toBeNull();
    expect(chip!.querySelector(".party-avatar")).not.toBeNull();
    expect(screen.getByText("forge-master")).toBeInTheDocument();
    expect(screen.getByText("Opus")).toBeInTheDocument();
  });

  it("renders the hero chip WITHOUT an avatar when claimed_by has no matching session in party (stale-evicted edge)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-R", claimed_by: "sess-ghost" })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-R"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-R`);
    const chip = container.querySelector(".card-drawer__hero-chip");
    expect(chip).not.toBeNull();
    expect(chip!.querySelector(".party-avatar")).toBeNull();
    expect(screen.getByText("sess-ghost")).toBeInTheDocument();
  });

  it("renders no hero chip when the card is unclaimed", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-S", claimed_by: null })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-S"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-S`);
    expect(container.querySelector(".card-drawer__hero-chip")).toBeNull();
  });
});
