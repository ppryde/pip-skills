import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import type { CardDetail } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  getCard: vi.fn(),
}));

import { getCard } from "../api/client";
import CardDetailDrawer from "./CardDetailDrawer";

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
    sections: {},
    body: "",
    ...overrides,
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
  });

  it("renders nothing when cardId is null", () => {
    render(<CardDetailDrawer cardId={null} onClose={() => {}} />);
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

    render(<CardDetailDrawer cardId="WF-A" onClose={() => {}} />);

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

  it("renders unknown section headings too — no hardcoded fixed set", async () => {
    vi.mocked(getCard).mockResolvedValueOnce(
      cardDetail({
        id: "WF-Z",
        sections: { "## Some New Heading": "Surprise content." },
      })
    );

    render(<CardDetailDrawer cardId="WF-Z" onClose={() => {}} />);

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

    render(<CardDetailDrawer cardId="WF-B" onClose={() => {}} />);

    expect(
      await screen.findByText("Just some raw markdown body.")
    ).toBeInTheDocument();
  });

  it("shows an error state with the thrown detail message when the fetch rejects", async () => {
    vi.mocked(getCard).mockRejectedValueOnce(new Error("card not found"));

    render(<CardDetailDrawer cardId="WF-C" onClose={() => {}} />);

    expect(await screen.findByText("card not found")).toBeInTheDocument();
  });

  it("closes via Esc keydown, overlay click, and the close button", async () => {
    vi.mocked(getCard).mockResolvedValue(cardDetail({ id: "WF-D" }));
    const onClose = vi.fn();
    render(<CardDetailDrawer cardId="WF-D" onClose={onClose} />);
    await screen.findByRole("dialog");

    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    await act(async () => {
      screen.getByRole("button", { name: /close/i }).click();
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("drops a stale getCard response: reopening a different card before the first resolves shows the LATER card's content, not the earlier one's", async () => {
    const first = deferred<CardDetail>();
    const second = deferred<CardDetail>();
    vi.mocked(getCard)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { rerender } = render(
      <CardDetailDrawer cardId="WF-A" onClose={() => {}} />
    );
    expect(getCard).toHaveBeenNthCalledWith(1, "WF-A");

    // Reopen a DIFFERENT card before A's fetch resolves — B's request is now
    // the "latest issued".
    rerender(<CardDetailDrawer cardId="WF-B" onClose={() => {}} />);
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
});
