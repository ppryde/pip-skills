import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  setPriority: vi.fn(),
}));

import { setPriority } from "../api/client";
import PrioritySelect from "./PrioritySelect";

const BOARD_RESPONSE = {} as BoardResponse;

/** Mimics `useBoard().mutate`: invokes `fn`, awaiting it, so tests can assert
 * both that the control routed through `mutate` (not client+setState
 * directly) AND what the underlying client call ended up being. */
function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

describe("<PrioritySelect/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("choosing P2 calls setPriority(id, 'P2') via mutate", () => {
    vi.mocked(setPriority).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(
      <PrioritySelect cardId="WF-1" value={null} mutate={mutate} inFlight={false} />
    );
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "P2" },
    });

    expect(setPriority).toHaveBeenCalledWith("WF-1", "P2");
    // Routes through mutate, not client+setState directly.
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
  });

  it("clearing the priority sends null", () => {
    vi.mocked(setPriority).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(
      <PrioritySelect cardId="WF-1" value="P1" mutate={mutate} inFlight={false} />
    );
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "" },
    });

    expect(setPriority).toHaveBeenCalledWith("WF-1", null);
  });

  it("disables the select while a mutation is in flight", () => {
    const mutate = makeMutate();
    render(
      <PrioritySelect cardId="WF-1" value={null} mutate={mutate} inFlight={true} />
    );
    expect(screen.getByLabelText("Priority")).toBeDisabled();
  });

  it("calls onMutated after the mutation settles (drawer refetch hook)", async () => {
    vi.mocked(setPriority).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    const onMutated = vi.fn();

    render(
      <PrioritySelect
        cardId="WF-1"
        value={null}
        mutate={mutate}
        inFlight={false}
        onMutated={onMutated}
      />
    );
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "P0" },
    });

    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(1));
  });
});
