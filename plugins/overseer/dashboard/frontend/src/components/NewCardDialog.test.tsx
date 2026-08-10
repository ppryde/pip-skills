import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({ createCard: vi.fn() }));
import { createCard } from "../api/client";
import NewCardDialog from "./NewCardDialog";

const CREATE_RESPONSE = {
  card_id: "WF-9",
  board: { project: "acme", cards: [], sprints: [], quarantined: [], label_colors: {} },
  context: { pct: null, threshold: null },
  limits: null,
} as unknown as BoardResponse;

// Live mutate double, same family as ThresholdControl.test.tsx/TopBar.test.tsx
// but honoring `{ rethrow }` exactly like the real useBoard.mutate (see
// board/useBoard.ts): a rejection from fn() propagates out of mutate() ONLY
// when the caller opted in with `{ rethrow: true }` — which is what
// NewCardDialog always passes — so this double no longer diverges from
// production behavior on the path under test.
function makeMutate() {
  return vi.fn(
    async (fn: () => Promise<BoardResponse>, opts?: { rethrow?: boolean }) => {
      try {
        await fn();
      } catch (e) {
        if (opts?.rethrow) throw e;
        // default: swallow, same as the real mutate()'s non-rethrow path.
      }
    }
  );
}

function open(mutate = makeMutate()) {
  const onClose = vi.fn();
  render(<NewCardDialog open onClose={onClose} mutate={mutate} />);
  return { onClose, mutate };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("<NewCardDialog/>", () => {
  it("renders nothing when closed", () => {
    render(<NewCardDialog open={false} onClose={vi.fn()} mutate={makeMutate()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the dialog when open", () => {
    open();
    expect(screen.getByRole("dialog", { name: /new card/i })).toBeInTheDocument();
  });

  it("disables Create when the title is empty or whitespace-only", () => {
    open();
    expect(screen.getByRole("button", { name: /create/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: /create/i })).toBeDisabled();
  });

  it("submitting a title routes the create through mutate with rethrow:true, which invokes createCard, then closes on success", async () => {
    vi.mocked(createCard).mockResolvedValue(CREATE_RESPONSE as never);
    const { onClose, mutate } = open();

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(expect.any(Function), { rethrow: true })
    );
    expect(createCard).toHaveBeenCalledWith({ title: "Fresh" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("builds CreateCardBody including only the provided optional fields", async () => {
    vi.mocked(createCard).mockResolvedValue(CREATE_RESPONSE as never);
    open();

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Fresh" } });
    fireEvent.change(screen.getByLabelText(/complexity/i), { target: { value: "M" } });
    fireEvent.change(screen.getByLabelText(/labels/i), {
      target: { value: "a, b ,, c" },
    });
    fireEvent.change(screen.getByLabelText(/goal/i), {
      target: { value: "  Ship it  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() =>
      expect(createCard).toHaveBeenCalledWith({
        title: "Fresh",
        complexity: "M",
        labels: ["a", "b", "c"],
        goal: "Ship it",
      })
    );
  });

  it("omits complexity/labels/goal from the body when left blank", async () => {
    vi.mocked(createCard).mockResolvedValue(CREATE_RESPONSE as never);
    open();

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() => expect(createCard).toHaveBeenCalledWith({ title: "Fresh" }));
  });

  it("shows a REAL inline error and keeps the dialog open (with the user's input intact) when createCard rejects — production behavior via mutate's rethrow:true", async () => {
    vi.mocked(createCard).mockRejectedValue(new Error("boom"));
    const { onClose, mutate } = open();

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/boom/i));
    expect(mutate).toHaveBeenCalledWith(expect.any(Function), { rethrow: true });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: /new card/i })).toBeInTheDocument();
    // The user's input is preserved, not blown away by the failed submit.
    expect(screen.getByLabelText(/title/i)).toHaveValue("Fresh");
  });

  it("Cancel closes without calling mutate", () => {
    const { onClose, mutate } = open();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("Escape closes the dialog", () => {
    const { onClose } = open();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("disables Create while the create is in flight, then re-enables", async () => {
    let resolveFn!: (v: BoardResponse) => void;
    vi.mocked(createCard).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFn = resolve as never;
        })
    );
    open();

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /create/i })).toBeDisabled()
    );

    resolveFn(CREATE_RESPONSE);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /create/i })).not.toBeDisabled()
    );
  });
});
