import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({
  setParent: vi.fn(),
  setDepends: vi.fn(),
}));

import { setParent, setDepends } from "../api/client";
import LinkEditor from "./LinkEditor";

const BOARD_RESPONSE = {} as BoardResponse;

function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

describe("<LinkEditor/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("setting a parent calls setParent(id, parentId) via mutate", () => {
    vi.mocked(setParent).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={[]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
      />
    );
    fireEvent.change(screen.getByLabelText("Parent"), {
      target: { value: "WF-1" },
    });

    expect(setParent).toHaveBeenCalledWith("WF-3", "WF-1");
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
  });

  it("clearing the parent sends null", () => {
    vi.mocked(setParent).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(
      <LinkEditor
        cardId="WF-3"
        parent="WF-1"
        dependsOn={[]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
      />
    );
    fireEvent.change(screen.getByLabelText("Parent"), {
      target: { value: "" },
    });

    expect(setParent).toHaveBeenCalledWith("WF-3", null);
  });

  it("excludes the card itself from the parent options", () => {
    const mutate = makeMutate();
    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={[]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
      />
    );
    const values = Array.from(
      screen.getByLabelText("Parent").querySelectorAll("option")
    ).map((o) => (o as HTMLOptionElement).value);
    expect(values).not.toContain("WF-3");
    expect(values).toContain("WF-1");
    expect(values).toContain("WF-2");
  });

  it("adding a dependency calls setDepends(id, {on}) via mutate", async () => {
    vi.mocked(setDepends).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={[]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
      />
    );
    fireEvent.change(screen.getByLabelText("Add dependency"), {
      target: { value: "WF-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));

    expect(setDepends).toHaveBeenCalledWith("WF-3", { on: "WF-2" });
    expect(mutate).toHaveBeenCalledWith(expect.any(Function));
    // The control clears its own draft select back to "— select —" once the
    // mutation settles — wait for that state update to flush cleanly.
    await waitFor(() =>
      expect(screen.getByLabelText("Add dependency")).toHaveValue("")
    );
  });

  it("removing a dependency calls setDepends(id, {off})", () => {
    vi.mocked(setDepends).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();

    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={["WF-2"]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
      />
    );
    fireEvent.click(
      screen.getByRole("button", { name: /remove dependency wf-2/i })
    );

    expect(setDepends).toHaveBeenCalledWith("WF-3", { off: "WF-2" });
  });

  it("excludes already-depended-on ids and self from the add-dependency options", () => {
    const mutate = makeMutate();
    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={["WF-2"]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
      />
    );
    const values = Array.from(
      screen.getByLabelText("Add dependency").querySelectorAll("option")
    ).map((o) => (o as HTMLOptionElement).value);
    expect(values).not.toContain("WF-3");
    expect(values).not.toContain("WF-2");
    expect(values).toContain("WF-1");
  });

  it("calls onMutated after a parent change settles", async () => {
    vi.mocked(setParent).mockResolvedValue(BOARD_RESPONSE);
    const mutate = makeMutate();
    const onMutated = vi.fn();

    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={[]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={false}
        onMutated={onMutated}
      />
    );
    fireEvent.change(screen.getByLabelText("Parent"), {
      target: { value: "WF-1" },
    });

    await waitFor(() => expect(onMutated).toHaveBeenCalledTimes(1));
  });

  it("disables all controls while a mutation is in flight", () => {
    const mutate = makeMutate();
    render(
      <LinkEditor
        cardId="WF-3"
        parent={null}
        dependsOn={["WF-2"]}
        allCardIds={["WF-1", "WF-2", "WF-3"]}
        mutate={mutate}
        inFlight={true}
      />
    );
    expect(screen.getByLabelText("Parent")).toBeDisabled();
    expect(screen.getByLabelText("Add dependency")).toBeDisabled();
    screen.getAllByRole("button").forEach((btn) => expect(btn).toBeDisabled());
  });
});
