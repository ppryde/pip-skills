import { afterEach, describe, expect, it, vi } from "vitest";
import type { BoardResponse } from "../api/types";

vi.mock("../api/client", () => ({
  setOrder: vi.fn(),
  move: vi.fn(),
}));

import { move, setOrder } from "../api/client";
import { runDropPlan } from "./runDropPlan";
import type { DropPlan } from "./dragPlan";

afterEach(() => {
  vi.clearAllMocks();
});

function boardResponse(pct: number): BoardResponse {
  return {
    board: { project: "p", cards: [], sprints: [], quarantined: [] },
    context: { pct, threshold: 80 },
    limits: null,
  };
}

describe("runDropPlan", () => {
  it("no-op plan never calls mutate (and never touches the api client), returns undefined", async () => {
    const mutate = vi.fn();
    const plan: DropPlan = { calls: [] };

    const result = await runDropPlan(plan, mutate);

    expect(mutate).not.toHaveBeenCalled();
    expect(setOrder).not.toHaveBeenCalled();
    expect(move).not.toHaveBeenCalled();
    expect(result).toBeUndefined();
  });

  it("a single setOrder call routes through mutate exactly once", async () => {
    vi.mocked(setOrder).mockResolvedValueOnce(boardResponse(1));
    // The test's `mutate` stand-in mirrors useBoard's real contract: it
    // invokes the passed function and awaits it — this is the ONE place a
    // mutation is allowed to reach the api client, never runDropPlan/Board
    // calling client + setState directly.
    const mutate = vi.fn(async (fn: () => Promise<BoardResponse>) => {
      await fn();
    });

    const plan: DropPlan = {
      calls: [{ kind: "setOrder", id: "WF-A", order: 15 }],
    };
    await runDropPlan(plan, mutate);

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(setOrder).toHaveBeenCalledWith("WF-A", 15);
    expect(move).not.toHaveBeenCalled();
  });

  it("a move+setOrder plan issues move THEN setOrder, both inside the SAME mutate() call, and applies the LAST (setOrder) response", async () => {
    const callOrder: string[] = [];
    vi.mocked(move).mockImplementation(async () => {
      callOrder.push("move");
      return boardResponse(10);
    });
    vi.mocked(setOrder).mockImplementation(async () => {
      callOrder.push("setOrder");
      return boardResponse(20);
    });

    const mutate = vi.fn(async (fn: () => Promise<BoardResponse>) => {
      await fn();
    });

    const plan: DropPlan = {
      calls: [
        { kind: "move", id: "WF-A", body: { stage: "planning" } },
        { kind: "setOrder", id: "WF-A", order: 15 },
      ],
    };
    const result = await runDropPlan(plan, mutate);

    expect(mutate).toHaveBeenCalledTimes(1); // ONE mutation entrypoint call
    expect(callOrder).toEqual(["move", "setOrder"]);
    expect(move).toHaveBeenCalledWith("WF-A", { stage: "planning" });
    expect(setOrder).toHaveBeenCalledWith("WF-A", 15);
    // The response mutate() ends up applying (and runDropPlan returns to its
    // caller for reconciliation) is the LAST call's response.
    expect(result?.context.pct).toBe(20);
  });

  it("a status-only move plan calls move with the given body", async () => {
    vi.mocked(move).mockResolvedValueOnce(boardResponse(5));
    const mutate = vi.fn(async (fn: () => Promise<BoardResponse>) => {
      await fn();
    });

    const plan: DropPlan = {
      calls: [{ kind: "move", id: "WF-A", body: { status: "parked" } }],
    };
    await runDropPlan(plan, mutate);

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(move).toHaveBeenCalledWith("WF-A", { status: "parked" });
    expect(setOrder).not.toHaveBeenCalled();
  });
});
