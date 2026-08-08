import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  setThreshold: vi.fn(),
}));

import { setThreshold } from "../api/client";
import ThresholdControl from "./ThresholdControl";

const BOARD_RESPONSE = {} as BoardResponse;

function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

describe("<ThresholdControl/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("submitting 80 calls setThreshold(80) via mutate", () => {
    vi.mocked(setThreshold).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(<ThresholdControl value={null} mutate={mutate} inFlight={false} />);
    fireEvent.change(screen.getByLabelText("Threshold"), {
      target: { value: "80" },
    });
    fireEvent.submit(screen.getByLabelText("Threshold").closest("form")!);

    expect(setThreshold).toHaveBeenCalledWith(80);
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
  });

  it("reflects the current context threshold value", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={65} mutate={mutate} inFlight={false} />);
    expect(screen.getByLabelText("Threshold")).toHaveValue(65);
  });

  it("does not call setThreshold when the input is not a finite number", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={null} mutate={mutate} inFlight={false} />);
    fireEvent.change(screen.getByLabelText("Threshold"), {
      target: { value: "" },
    });
    fireEvent.submit(screen.getByLabelText("Threshold").closest("form")!);

    expect(setThreshold).not.toHaveBeenCalled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("disables the input and submit button while a mutation is in flight", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={50} mutate={mutate} inFlight={true} />);
    expect(screen.getByLabelText("Threshold")).toBeDisabled();
    expect(screen.getByRole("button", { name: /set/i })).toBeDisabled();
  });
});
