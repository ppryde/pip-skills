import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

vi.mock("../api/client", () => ({
  setAttributes: vi.fn(),
}));

import { setAttributes } from "../api/client";
import AttributesEditor, { parseTokens } from "./AttributesEditor";
import ComplexitySelect from "./ComplexitySelect";

const BOARD_RESPONSE = {} as BoardResponse;

function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

describe("parseTokens", () => {
  it("reads counts the way the CLI does", () => {
    expect(parseTokens("400k")).toBe(400_000);
    expect(parseTokens("1.2M")).toBe(1_200_000);
    expect(parseTokens(" 999 ")).toBe(999);
    expect(parseTokens("")).toBeNull();
    expect(parseTokens("lots")).toBeUndefined();
  });
});

describe("<AttributesEditor/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(setAttributes).mockResolvedValue(BOARD_RESPONSE);
  });

  it("sends only the fields that changed, via mutate, then refetches", async () => {
    const mutate = makeMutate();
    const onMutated = vi.fn();
    render(
      <AttributesEditor cardId="WF-1" sprint={null} estimate={400_000} mutate={mutate} inFlight={false} onMutated={onMutated} />
    );
    expect(screen.getByLabelText("Estimate")).toHaveValue("400k");
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled(); // nothing changed yet

    fireEvent.change(screen.getByLabelText("Sprint"), { target: { value: "S-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(onMutated).toHaveBeenCalled());
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(setAttributes).toHaveBeenCalledWith("WF-1", { sprint: "S-2" });
  });

  it("clears a field with null and parses token suffixes", async () => {
    const mutate = makeMutate();
    render(<AttributesEditor cardId="WF-1" sprint="S-1" estimate={null} mutate={mutate} inFlight={false} />);

    fireEvent.change(screen.getByLabelText("Sprint"), { target: { value: "  " } });
    fireEvent.change(screen.getByLabelText("Estimate"), { target: { value: "1.5M" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(setAttributes).toHaveBeenCalledWith("WF-1", { sprint: null, estimate: 1_500_000 }));
  });

  it("refuses an estimate it cannot read, without calling the API", async () => {
    const mutate = makeMutate();
    render(<AttributesEditor cardId="WF-1" sprint={null} estimate={null} mutate={mutate} inFlight={false} />);

    fireEvent.change(screen.getByLabelText("Estimate"), { target: { value: "lots" } });
    expect(screen.getByLabelText("Estimate")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    fireEvent.submit(screen.getByLabelText("Estimate").closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent(/400k/);
    expect(setAttributes).not.toHaveBeenCalled();
  });

  it("resets its drafts when the card's values change underneath it", () => {
    const { rerender } = render(
      <AttributesEditor cardId="WF-1" sprint="S-1" estimate={null} mutate={makeMutate()} inFlight={false} />
    );
    fireEvent.change(screen.getByLabelText("Sprint"), { target: { value: "draft" } });
    rerender(<AttributesEditor cardId="WF-1" sprint="S-9" estimate={2_000} mutate={makeMutate()} inFlight={false} />);
    expect(screen.getByLabelText("Sprint")).toHaveValue("S-9");
    expect(screen.getByLabelText("Estimate")).toHaveValue("2k");
  });
});

describe("<ComplexitySelect/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(setAttributes).mockResolvedValue(BOARD_RESPONSE);
  });

  it("choosing L sends {complexity: 'L'} via mutate; the blank option clears", async () => {
    const mutate = makeMutate();
    const onMutated = vi.fn();
    render(<ComplexitySelect cardId="WF-1" value="S" mutate={mutate} inFlight={false} onMutated={onMutated} />);
    const select = screen.getByLabelText("Complexity");
    expect(select).toHaveValue("S");

    fireEvent.change(select, { target: { value: "L" } });
    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(1));
    expect(setAttributes).toHaveBeenCalledWith("WF-1", { complexity: "L" });

    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(2));
    expect(setAttributes).toHaveBeenLastCalledWith("WF-1", { complexity: null });
    expect(mutate).toHaveBeenCalledTimes(2);
  });

  it("is disabled while a mutation is in flight", () => {
    render(<ComplexitySelect cardId="WF-1" value={null} mutate={makeMutate()} inFlight />);
    expect(screen.getByLabelText("Complexity")).toBeDisabled();
  });
});
