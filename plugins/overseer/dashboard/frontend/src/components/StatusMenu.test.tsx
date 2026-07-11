import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  park: vi.fn(),
  unpark: vi.fn(),
  move: vi.fn(),
}));

import { park, unpark, move } from "../api/client";
import StatusMenu from "./StatusMenu";

const BOARD_RESPONSE = {} as BoardResponse;

function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

describe("<StatusMenu/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("park calls park(id) via mutate", () => {
    vi.mocked(park).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /park/i }));

    expect(park).toHaveBeenCalledWith("WF-1");
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
  });

  it("unpark calls unpark(id) when the card is parked", () => {
    vi.mocked(unpark).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="parked" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /unpark/i }));

    expect(unpark).toHaveBeenCalledWith("WF-1");
  });

  it("done calls move(id, {status:'done'})", () => {
    vi.mocked(move).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /^done$/i }));

    expect(move).toHaveBeenCalledWith("WF-1", { status: "done" });
  });

  it("abandon calls move(id, {status:'abandoned'})", () => {
    vi.mocked(move).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /^abandon$/i }));

    expect(move).toHaveBeenCalledWith("WF-1", { status: "abandoned" });
  });

  it("block with a non-empty reason calls move(id, {status:'blocked', reason})", () => {
    vi.mocked(move).mockResolvedValue(BOARD_RESPONSE);
    vi.spyOn(window, "prompt").mockReturnValue("waiting on WF-2");
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /block/i }));

    expect(move).toHaveBeenCalledWith("WF-1", {
      status: "blocked",
      reason: "waiting on WF-2",
    });
  });

  it("block with an empty reason makes NO call", () => {
    vi.spyOn(window, "prompt").mockReturnValue("");
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /block/i }));

    expect(move).not.toHaveBeenCalled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("block cancelled (prompt returns null) makes NO call", () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /block/i }));

    expect(move).not.toHaveBeenCalled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("block with a whitespace-only reason makes NO call", () => {
    vi.spyOn(window, "prompt").mockReturnValue("   ");
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /block/i }));

    expect(move).not.toHaveBeenCalled();
  });

  it("unblock (from blocked) calls move(id, {status:'planned'})", () => {
    vi.mocked(move).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="blocked" mutate={mutate} inFlight={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /unblock/i }));

    expect(move).toHaveBeenCalledWith("WF-1", { status: "planned" });
  });

  it("calls onMutated after a mutation settles", async () => {
    vi.mocked(park).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    const onMutated = vi.fn();
    render(
      <StatusMenu
        cardId="WF-1"
        status="planned"
        mutate={mutate}
        inFlight={false}
        onMutated={onMutated}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /park/i }));

    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(1));
  });

  it("does NOT call onMutated when block is cancelled", () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    const mutate = makeMutate();
    const onMutated = vi.fn();
    render(
      <StatusMenu
        cardId="WF-1"
        status="planned"
        mutate={mutate}
        inFlight={false}
        onMutated={onMutated}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /block/i }));

    expect(onMutated).not.toHaveBeenCalled();
  });

  it("disables all buttons while a mutation is in flight", () => {
    const mutate = makeMutate();
    render(
      <StatusMenu cardId="WF-1" status="planned" mutate={mutate} inFlight={true} />
    );
    screen.getAllByRole("button").forEach((btn) => expect(btn).toBeDisabled());
  });
});
