import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BoardResponse, CardDetail, SessionSummary } from "../api/types";
import type { PartyMember } from "../board/party";

// Mock the SOLE api client module — no real fetch in this test. Includes the
// mutation wrappers the wired-in controls (PrioritySelect/LinkEditor/
// StatusMenu) import, even though most tests here never trigger them.
vi.mock("../api/client", () => ({
  getCard: vi.fn(),
  editCard: vi.fn(),
  setPriority: vi.fn(),
  setParent: vi.fn(),
  setDepends: vi.fn(),
  park: vi.fn(),
  unpark: vi.fn(),
  move: vi.fn(),
  getSessions: vi.fn(),
  claimCard: vi.fn(),
  unclaimCard: vi.fn(),
  setLabels: vi.fn(),
  pullChildren: vi.fn(),
}));

import {
  getCard,
  getSessions,
  setPriority,
  setLabels,
  editCard,
  pullChildren,
} from "../api/client";
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
    created: "",
    updated: "",
    checklist: [],
    labels: [],
    links: [],
    pr: null,
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

  it("threads cardTitles through to LinkEditor's depends-on picker (WF-081)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-B", title: "Card B", depends_on: [] })
    );

    render(
      <CardDetailDrawer
        cardId="WF-B"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={["WF-B", "WF-Z"]}
        cardTitles={{ "WF-Z": "Zap the thing" }}
        party={[]}
      />
    );

    await screen.findByText("Card B");
    const options = Array.from(
      screen.getByLabelText("Add dependency").querySelectorAll("option")
    ) as HTMLOptionElement[];
    const wfZ = options.find((o) => o.value === "WF-Z");
    expect(wfZ?.textContent).toBe("WF-Z — Zap the thing");
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

    expect(getCard).toHaveBeenCalledWith("WF-A");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();

    expect(await screen.findByText("Do the thing")).toBeInTheDocument();
    expect(screen.getByText("Goal")).toBeInTheDocument();
    expect(screen.getByText("Ship the feature.")).toBeInTheDocument();
    expect(screen.getByText("Plan")).toBeInTheDocument();
    expect(screen.getByText("Do steps 1, 2, 3.")).toBeInTheDocument();
    expect(screen.getByText("P1")).toBeInTheDocument();
    expect(screen.getByText(/in-flight/)).toBeInTheDocument();
    // Stage now renders as the title-row chip (STAGE_LABELS) rather than
    // appended to the status-fact text — see CardDetailDrawer's stage-chip.
    // The banner pill ALSO reads "Implementation" (WF-030 chunk 2), so this
    // scopes to the chip specifically rather than screen.getByText, which
    // would ambiguously match both.
    expect(
      container.querySelector(".card-drawer__stage-chip")
    ).toHaveTextContent("Implementation");
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

  it("renders a clickable, safely-attributed PR anchor for an http(s) pr (WF-073)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-A", pr: "https://github.com/org/repo/pull/42" })
    );

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
    const chip = container.querySelector("a.card-drawer__pr-chip");
    expect(chip).not.toBeNull();
    expect(chip).toHaveAttribute(
      "href",
      "https://github.com/org/repo/pull/42"
    );
    expect(chip).toHaveAttribute("target", "_blank");
    expect(chip).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders non-link PR badge text for a bare (non-http) pr ref (WF-073)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-A", pr: "#42" })
    );

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
    expect(container.querySelector("a.card-drawer__pr-chip")).toBeNull();
    const chip = container.querySelector("span.card-drawer__pr-chip");
    expect(chip).not.toBeNull();
    expect(chip).toHaveTextContent("#42");
  });

  it("renders no PR chip when the card carries no pr (WF-073)", async () => {
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
    expect(container.querySelector(".card-drawer__pr-chip")).toBeNull();
  });

  it("renders a chip for each of the card's labels via the editable LabelEditor (F1, WF-058)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-A", labels: ["policy", "architecture"] })
    );

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
    const chips = container.querySelectorAll(".label-editor__chip");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("policy");
    expect(chips[1]).toHaveTextContent("architecture");
  });

  it("renders a read-only link per entry in a Links section (F8, WF-065)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-A",
        links: [
          { label: "Design doc", path: "https://example.com/design" },
          { label: "PR", path: "https://example.com/pr/1" },
        ],
      })
    );

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
    expect(screen.getByText("Links")).toBeInTheDocument();
    const links = container.querySelectorAll(".card-drawer__links-list a");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveTextContent("Design doc");
    expect(links[0]).toHaveAttribute(
      "href",
      "https://example.com/design"
    );
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(links[1]).toHaveTextContent("PR");
    expect(links[1]).toHaveAttribute("href", "https://example.com/pr/1");
  });

  it("renders a non-http(s) link path as inert text, not an anchor (security fix, PR5 final review)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-A",
        links: [
          { label: "evil js", path: "javascript:alert(1)" },
          { label: "PR", path: "https://example.com/pr/1" },
        ],
      })
    );

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
    const anchors = container.querySelectorAll(".card-drawer__links-list a");
    expect(anchors).toHaveLength(1);
    expect(anchors[0]).toHaveTextContent("PR");
    expect(anchors[0]).toHaveAttribute("href", "https://example.com/pr/1");

    const items = container.querySelectorAll(".card-drawer__links-list li");
    expect(items[0].querySelector("a")).toBeNull();
    expect(items[0]).toHaveTextContent("evil js");
  });

  it("renders nothing for Links when the card carries no links", async () => {
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
    expect(screen.queryByText("Links")).toBeNull();
    expect(container.querySelector(".card-drawer__links")).toBeNull();
  });

  it("renders the label editor with no chips (just the add-input) when the card carries no labels", async () => {
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
    expect(container.querySelector(".label-editor__chip")).toBeNull();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("saves an added label through mutate() (board tiles) AND re-fetches the open card (refetchDetail), same as the sibling controls", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-LBL", title: "Label me", labels: ["policy"] })
    );
    vi.mocked(setLabels).mockResolvedValueOnce(BOARD_RESPONSE);
    // The refetch after the save returns updated content — proves it's a
    // REAL second `getCard` call, not just a re-render of stale state.
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-LBL",
        title: "Label me",
        labels: ["policy", "arch"],
      })
    );

    // liveMutate() actually invokes the function it's given (unlike
    // noopMutate) — needed here because the fix under test is that the
    // label save is routed THROUGH `mutate`, exactly like PrioritySelect/
    // LinkEditor/ClaimControl, not called directly.
    const mutate = liveMutate();
    render(
      <CardDetailDrawer
        cardId="WF-LBL"
        onClose={() => {}}
        mutate={mutate}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText("Label me");
    expect(getCard).toHaveBeenCalledTimes(1);

    const input = screen.getByRole("textbox");
    await act(async () => {
      fireEvent.change(input, { target: { value: "arch" } });
      fireEvent.keyDown(input, { key: "Enter" });
    });

    // The mutate path is exercised — this is the SAME `mutate` prop
    // PrioritySelect/LinkEditor/ClaimControl call, and it's what keeps the
    // board's own state (and thus TileShell's tiles) in sync; bypassing it
    // was the bug being fixed here.
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
    expect(setLabels).toHaveBeenCalledWith("WF-LBL", ["policy", "arch"]);
    await waitFor(() => expect(getCard).toHaveBeenCalledTimes(2));
  });

  it("edits title and body and saves via editCard, routed through mutate() (board tiles) AND re-fetches the open card (refetchDetail), same as the label save", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-1", title: "Old", body: "old body" })
    );
    vi.mocked(editCard).mockResolvedValueOnce(BOARD_RESPONSE);
    // The refetch after the save returns updated content — proves it's a
    // REAL second `getCard` call, not just a re-render of stale state.
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-1", title: "New title", body: "new body" })
    );

    // liveMutate() actually invokes the function it's given — needed here
    // because the save must be routed THROUGH `mutate`, exactly like
    // PrioritySelect/LinkEditor/ClaimControl/LabelEditor, not called
    // directly (Task 7 review finding).
    const mutate = liveMutate();
    render(
      <CardDetailDrawer
        cardId="WF-1"
        onClose={() => {}}
        mutate={mutate}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText("Old");
    expect(getCard).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: "New title" },
    });
    fireEvent.change(screen.getByLabelText(/body/i), {
      target: { value: "new body" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save/i }));
    });

    expect(mutate).toHaveBeenCalledWith(expect.any(Function), { rethrow: true });
    expect(editCard).toHaveBeenCalledWith("WF-1", {
      title: "New title",
      body: "new body",
    });
    await waitFor(() => expect(getCard).toHaveBeenCalledTimes(2));
    await screen.findByText("New title");
  });

  it("keeps edit mode open, preserves the draft, and shows an inline error when the save rejects — no silent draft loss on failure (fix-up, PR3 dual review)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-1E", title: "Old title", body: "old body" })
    );
    vi.mocked(editCard).mockRejectedValueOnce(new Error("save failed"));

    // liveMutate() forwards fn()'s rejection unconditionally (see its doc
    // comment) — the same shape a rethrowing `useBoard.mutate` has for a
    // caller that always passes `{ rethrow: true }`, which is what
    // `saveEdit` does.
    const mutate = liveMutate();
    render(
      <CardDetailDrawer
        cardId="WF-1E"
        onClose={() => {}}
        mutate={mutate}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText("Old title");

    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: "Draft title" },
    });
    fireEvent.change(screen.getByLabelText(/body/i), {
      target: { value: "draft body" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save/i }));
    });

    expect(mutate).toHaveBeenCalledWith(expect.any(Function), { rethrow: true });
    // Edit mode did NOT fall through to the read view, and both drafts
    // survive exactly as typed — this is the bug being fixed.
    expect(screen.getByLabelText(/title/i)).toHaveValue("Draft title");
    expect(screen.getByLabelText(/body/i)).toHaveValue("draft body");
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
    // No refetch fired for a failed save — getCard only ran once, at open.
    expect(getCard).toHaveBeenCalledTimes(1);
  });

  it("disables Save when the title draft is empty, and Cancel restores the read view without saving", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-2", title: "Keep me", body: "keep body" })
    );

    render(
      <CardDetailDrawer
        cardId="WF-2"
        onClose={() => {}}
        mutate={liveMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText("Keep me");

    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: "   " },
    });
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: "Changed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(editCard).not.toHaveBeenCalled();
    expect(screen.getByText("Keep me")).toBeInTheDocument();
    expect(screen.queryByLabelText(/title/i)).not.toBeInTheDocument();
  });

  it("resets edit drafts and exits edit mode when switching to a different card", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-3", title: "Card three", body: "three body" })
    );

    const { rerender } = render(
      <CardDetailDrawer
        cardId="WF-3"
        onClose={() => {}}
        mutate={liveMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText("Card three");

    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: "Leaked draft" },
    });

    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-4", title: "Card four", body: "four body" })
    );
    rerender(
      <CardDetailDrawer
        cardId="WF-4"
        onClose={() => {}}
        mutate={liveMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText("Card four");
    // Not in edit mode any more, and no leaked draft from the prior card.
    expect(screen.queryByLabelText(/title/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Leaked draft")).not.toBeInTheDocument();
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

    expect(screen.getByRole("button", { name: /quest/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByText("thing").tagName).toBe("EM"); // rendered markdown

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /scroll/i }));
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
      fireEvent.click(screen.getByRole("button", { name: /scroll/i }));
    });
    expect(screen.getByRole("button", { name: /scroll/i })).toHaveAttribute(
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
    expect(screen.getByRole("button", { name: /quest/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("renders a Sub-quests section with the FULL (unwindowed) checklist when non-empty", async () => {
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

    expect(await screen.findByText("Sub-quests")).toBeInTheDocument();
    expect(screen.getByText("1 / 6")).toBeInTheDocument(); // done/total count
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

  it("renders no Sub-quests section (or Journey progress bar) when the checklist is empty", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-K", title: "No tasks", checklist: [] })
    );

    const { container } = render(
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
    expect(screen.queryByText("Sub-quests")).not.toBeInTheDocument();
    expect(container.querySelector(".card-drawer__journey")).toBeNull();
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
    expect(container.querySelectorAll(".card-drawer__star").length).toBe(4);
    expect(
      container.querySelectorAll(".card-drawer__star--filled").length
    ).toBe(2);
  });

  it("renders 4 filled stars for an XL card — 4-band scale, distinct from L (D2)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-XL", complexity: "XL" })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-XL"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-XL`);
    expect(container.querySelectorAll(".card-drawer__star").length).toBe(4);
    expect(
      container.querySelectorAll(".card-drawer__star--filled").length
    ).toBe(4);
    expect(
      container.querySelectorAll(".card-drawer__star--empty").length
    ).toBe(0);
  });

  it("renders 3 filled + 1 empty star for an L card", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-LL", complexity: "L" })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-LL"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-LL`);
    expect(container.querySelectorAll(".card-drawer__star").length).toBe(4);
    expect(
      container.querySelectorAll(".card-drawer__star--filled").length
    ).toBe(3);
    expect(
      container.querySelectorAll(".card-drawer__star--empty").length
    ).toBe(1);
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

  it("Journey progress bar reflects done/total over the FULL checklist (WF-030 chunk 4)", async () => {
    const checklist = Array.from({ length: 8 }, (_, i) => ({
      task: String(i + 1),
      subject: `Task ${i + 1}`,
      status: i < 2 ? "completed" : "pending",
    }));
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-T", checklist })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-T"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-T`);
    expect(screen.getByText("Journey progress")).toBeInTheDocument();
    const track = container.querySelector(".card-drawer__journey-track");
    expect(track).toHaveAttribute("data-progress-pct", "25"); // 2/8
    expect(screen.getByText("2 / 8")).toBeInTheDocument(); // Sub-quests count
  });

  it("Journey progress shows 0% for an all-pending checklist and 100% for an all-completed one", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-U",
        checklist: [
          { task: "1", subject: "A", status: "pending" },
          { task: "2", subject: "B", status: "pending" },
        ],
      })
    );
    const { container: c0 } = render(
      <CardDetailDrawer
        cardId="WF-U"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText(`Title WF-U`);
    expect(
      c0.querySelector(".card-drawer__journey-track")
    ).toHaveAttribute("data-progress-pct", "0");

    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-V",
        checklist: [
          { task: "1", subject: "A", status: "completed" },
          { task: "2", subject: "B", status: "completed" },
        ],
      })
    );
    const { container: c100 } = render(
      <CardDetailDrawer
        cardId="WF-V"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );
    await screen.findByText(`Title WF-V`);
    expect(
      c100.querySelector(".card-drawer__journey-track")
    ).toHaveAttribute("data-progress-pct", "100");
  });

  it("renders the locked-behind pill in the Quest-tab body (after the sub-quests panel), not the header", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-W",
        ready: false,
        depends_on: ["WF-001", "WF-002"],
      })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-W"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-W`);
    const badge = screen.getByText(/waiting on WF-001, WF-002/);
    expect(badge).toBeInTheDocument();
    // Lives in .card-drawer__locked, NOT .card-drawer__facts (the header
    // meta row) — see chunk 2's Decisions on placement.
    expect(
      container.querySelector(".card-drawer__locked .dep-badge")
    ).not.toBeNull();
    expect(
      container.querySelector(".card-drawer__facts .dep-badge")
    ).toBeNull();
  });

  it("renders no locked-behind pill when the card has no dependencies", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({ id: "WF-X", ready: true, depends_on: [] })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-X"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-X`);
    expect(container.querySelector(".dep-badge")).toBeNull();
  });

  it("renders a well-formed Progress log section as a quest-log timeline (WF-030 chunk 9, stretch)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-Y",
        sections: {
          "## Progress log":
            "- 2026-07-14T08:19 — comms: subagent mode (~0 tokens)\n" +
            "- 2026-07-14T08:37 — plan-review passed (~165k tokens)",
        },
      })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-Y"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-Y`);
    expect(container.querySelector(".card-drawer__quest-log")).not.toBeNull();
    expect(
      container.querySelectorAll(".card-drawer__quest-log-entry").length
    ).toBe(2);
    expect(screen.getByText("comms: subagent mode")).toBeInTheDocument();
    expect(screen.getByText("2026-07-14T08:37")).toBeInTheDocument();
  });

  it("falls back to plain MarkdownView rendering when the Progress log section doesn't parse cleanly", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-Z2",
        sections: {
          "## Progress log":
            "- 2026-07-14T08:19 — comms: subagent mode (~0 tokens)\n" +
            "not a parseable line",
        },
      })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-Z2"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-Z2`);
    expect(container.querySelector(".card-drawer__quest-log")).toBeNull();
    // The raw section text still renders — full plain-section fallback,
    // never a partial timeline mixed with a partial dump.
    expect(
      screen.getByText(/comms: subagent mode/)
    ).toBeInTheDocument();
    expect(screen.getByText(/not a parseable line/)).toBeInTheDocument();
  });

  it("gates Journey progress + Sub-quests panel + locked pill to the Quest view — absent under Scroll (impl-review round 1)", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-AA",
        ready: false,
        depends_on: ["WF-001"],
        checklist: [
          { task: "1", subject: "Write the design doc", status: "completed" },
          { task: "2", subject: "Implement", status: "pending" },
        ],
        body: "# Goal\nRaw body text.",
      })
    );

    const { container } = render(
      <CardDetailDrawer
        cardId="WF-AA"
        onClose={() => {}}
        mutate={noopMutate()}
        inFlight={false}
        allCardIds={[]}
        party={[]}
      />
    );

    await screen.findByText(`Title WF-AA`);

    // Quest view (default): all three present.
    expect(container.querySelector(".card-drawer__journey")).not.toBeNull();
    expect(screen.getByText("Sub-quests")).toBeInTheDocument();
    expect(screen.getByText(/waiting on WF-001/)).toBeInTheDocument();

    // Switch to Scroll — all three gone, only the markdown card remains.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /scroll/i }));
    });

    expect(container.querySelector(".card-drawer__journey")).toBeNull();
    expect(screen.queryByText("Sub-quests")).not.toBeInTheDocument();
    expect(screen.queryByText(/waiting on WF-001/)).not.toBeInTheDocument();
    expect(screen.getByTestId("card-source")).toBeInTheDocument();

    // The tab bar itself survives the swap (stays outside the gated block).
    expect(
      screen.getByRole("group", { name: /body view/i })
    ).toBeInTheDocument();

    // Switch back to Quest — all three return.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /quest/i }));
    });
    expect(container.querySelector(".card-drawer__journey")).not.toBeNull();
    expect(screen.getByText("Sub-quests")).toBeInTheDocument();
    expect(screen.getByText(/waiting on WF-001/)).toBeInTheDocument();
  });

  describe("Pull children control (F9, WF-066)", () => {
    it("renders a 'Pull children' button when the card is an epic", async () => {
      vi.mocked(getCard).mockResolvedValueOnce(
        cardDetail({ id: "WF-EPIC", title: "Epic card", is_epic: true })
      );

      render(
        <CardDetailDrawer
          cardId="WF-EPIC"
          onClose={() => {}}
          mutate={noopMutate()}
          inFlight={false}
          allCardIds={[]}
          party={[]}
        />
      );

      await screen.findByText("Epic card");
      expect(
        screen.getByRole("button", { name: /pull children/i })
      ).toBeInTheDocument();
    });

    it("renders NO 'Pull children' button when the card is not an epic", async () => {
      vi.mocked(getCard).mockResolvedValueOnce(
        cardDetail({ id: "WF-LEAF", title: "Leaf card", is_epic: false })
      );

      render(
        <CardDetailDrawer
          cardId="WF-LEAF"
          onClose={() => {}}
          mutate={noopMutate()}
          inFlight={false}
          allCardIds={[]}
          party={[]}
        />
      );

      await screen.findByText("Leaf card");
      expect(
        screen.queryByRole("button", { name: /pull children/i })
      ).not.toBeInTheDocument();
    });

    it("on confirm accept, routes pullChildren through mutate() then refetches the open card", async () => {
      vi.mocked(getCard).mockResolvedValueOnce(
        cardDetail({ id: "WF-EPIC2", title: "Epic two", is_epic: true })
      );
      vi.mocked(pullChildren).mockResolvedValueOnce(BOARD_RESPONSE);
      // The refetch after the pull returns updated content — proves it's a
      // REAL second `getCard` call, not just a re-render of stale state.
      vi.mocked(getCard).mockResolvedValueOnce(
        cardDetail({ id: "WF-EPIC2", title: "Epic two", is_epic: true })
      );
      vi.spyOn(window, "confirm").mockReturnValue(true);

      // liveMutate() actually invokes the function it's given — needed here
      // because the control must route THROUGH `mutate`, exactly like the
      // sibling controls, not call `pullChildren` directly.
      const mutate = liveMutate();
      render(
        <CardDetailDrawer
          cardId="WF-EPIC2"
          onClose={() => {}}
          mutate={mutate}
          inFlight={false}
          allCardIds={[]}
          party={[]}
        />
      );
      await screen.findByText("Epic two");
      expect(getCard).toHaveBeenCalledTimes(1);

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /pull children/i })
        );
      });

      expect(window.confirm).toHaveBeenCalledWith(
        "Pull all live children into this epic's column?"
      );
      expect(mutate).toHaveBeenCalledWith(expect.any(Function));
      expect(pullChildren).toHaveBeenCalledWith("WF-EPIC2");
      await waitFor(() => expect(getCard).toHaveBeenCalledTimes(2));
    });

    it("on confirm decline, calls neither mutate nor pullChildren", async () => {
      vi.mocked(getCard).mockResolvedValueOnce(
        cardDetail({ id: "WF-EPIC3", title: "Epic three", is_epic: true })
      );
      vi.spyOn(window, "confirm").mockReturnValue(false);

      const mutate = liveMutate();
      render(
        <CardDetailDrawer
          cardId="WF-EPIC3"
          onClose={() => {}}
          mutate={mutate}
          inFlight={false}
          allCardIds={[]}
          party={[]}
        />
      );
      await screen.findByText("Epic three");

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /pull children/i })
        );
      });

      expect(window.confirm).toHaveBeenCalled();
      expect(mutate).not.toHaveBeenCalled();
      expect(pullChildren).not.toHaveBeenCalled();
      // No refetch fired either — still just the initial open fetch.
      expect(getCard).toHaveBeenCalledTimes(1);
    });
  });

  describe("body/source legibility (WF-082 — no shouty pixel font)", () => {
    // CardDetailDrawer.tsx never applies text-transform to body content, and
    // vitest's jsdom environment doesn't run the real stylesheet cascade
    // (this test file never imports styles.css — only main.tsx does, and
    // even then CSS imports are stubbed under vitest) — so the "renders
    // ALL-CAPS" bug can't be caught via getComputedStyle here. The actual
    // cause is `--qb-font-mono` ("Silkscreen", a decorative pixel/badge
    // font) being applied to the FULL body content in the edit textarea and
    // Scroll/source view, which reads as shouting caps even though the text
    // itself is untouched — that font is reserved elsewhere in styles.css
    // for small badges (MD tag, hero-class chip, quest-log stamp) only.
    // Assert those two rules directly against the stylesheet text.
    const css = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..", "styles.css"),
      "utf8"
    );

    function ruleBody(selector: string): string {
      const escaped = selector.replace(/[.]/g, "\\.");
      const match = css.match(new RegExp(`${escaped}\\s*{([^}]*)}`));
      if (!match) {
        throw new Error(`selector ${selector} not found in styles.css`);
      }
      return match[1];
    }

    it("edit textarea does not use the decorative pixel badge font", () => {
      const rule = ruleBody(".card-drawer__body-textarea");
      expect(rule).not.toMatch(/Silkscreen|--qb-font-mono/);
    });

    it("source/scroll view does not use the decorative pixel badge font", () => {
      const rule = ruleBody(".card-drawer__source");
      expect(rule).not.toMatch(/Silkscreen|--qb-font-mono/);
    });
  });
});
