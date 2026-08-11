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

  it("selecting 65 calls setThreshold(65) via mutate, immediately (no Set button)", () => {
    vi.mocked(setThreshold).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(<ThresholdControl value={null} mutate={mutate} inFlight={false} />);
    fireEvent.change(screen.getByLabelText("Threshold"), {
      target: { value: "65" },
    });

    expect(setThreshold).toHaveBeenCalledWith(65);
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
  });

  it("reflects the current context threshold value", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={65} mutate={mutate} inFlight={false} />);
    expect(screen.getByLabelText("Threshold")).toHaveValue("65");
  });

  it("shows a disabled '—' placeholder and does not call setThreshold when value is null", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={null} mutate={mutate} inFlight={false} />);
    const select = screen.getByLabelText("Threshold") as HTMLSelectElement;
    expect(select).toHaveValue("");
    expect(setThreshold).not.toHaveBeenCalled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("disables the select while a mutation is in flight", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={50} mutate={mutate} inFlight={true} />);
    expect(screen.getByLabelText("Threshold")).toBeDisabled();
  });

  it("includes an out-of-step legacy value as its own option instead of hiding it", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={42} mutate={mutate} inFlight={false} />);
    const select = screen.getByLabelText("Threshold") as HTMLSelectElement;
    expect(select).toHaveValue("42");
    expect(screen.getByRole("option", { name: "42%" })).toBeInTheDocument();
  });

  it("renders 5%-step options from 5 to 95", () => {
    const mutate = makeMutate();
    render(<ThresholdControl value={45} mutate={mutate} inFlight={false} />);
    expect(screen.getByRole("option", { name: "5%" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "95%" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "100%" })).not.toBeInTheDocument();
  });
});
