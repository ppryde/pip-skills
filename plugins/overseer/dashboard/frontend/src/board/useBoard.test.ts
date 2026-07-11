import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

vi.mock("../api/client", () => ({
  getBoard: vi.fn(),
}));

import { getBoard } from "../api/client";
import { useBoard } from "./useBoard";

function boardResponse(pct: number): BoardResponse {
  return {
    board: { project: "p", cards: [], sprints: [], quarantined: [] },
    context: { pct, threshold: 80 },
    limits: null,
  };
}

/** A promise whose resolve is exposed so the test drives ordering explicitly. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("useBoard.mutate() in-flight lock", () => {
  it("clears inFlight even when a refresh RACES an in-flight mutation (bumping the shared counter)", async () => {
    const mockedGetBoard = vi.mocked(getBoard);

    // 1) Mount load resolves immediately so `loading` settles to false.
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // 2) Start a mutation whose fn() we control — inFlight goes true, and the
    //    shared request counter is now at the mutation's issued id.
    const mut = deferred<BoardResponse>();
    let mutateDone: Promise<void>;
    act(() => {
      mutateDone = result.current.mutate(() => mut.promise);
    });
    await waitFor(() => expect(result.current.inFlight).toBe(true));

    // 3) A refresh races mid-flight — this bumps the SHARED counter past the
    //    mutation's id (the exact scenario that used to strand the lock).
    const ref = deferred<BoardResponse>();
    mockedGetBoard.mockReturnValueOnce(ref.promise);
    let refreshDone: Promise<void>;
    act(() => {
      refreshDone = result.current.refresh();
    });

    // 4) Now the ORIGINAL mutation resolves — its id is stale, so its response
    //    must NOT be applied, but the lock MUST clear regardless.
    await act(async () => {
      mut.resolve(boardResponse(99)); // pct=99 must be dropped (stale)
      await mutateDone;
    });

    // The bug: inFlight would still be true here. The fix: it is false.
    expect(result.current.inFlight).toBe(false);

    // Stale mutation response was dropped (not applied over fresher state).
    expect(result.current.context?.pct).not.toBe(99);

    // Let the racing refresh settle so its response is the one that wins.
    await act(async () => {
      ref.resolve(boardResponse(55));
      await refreshDone;
    });
    expect(result.current.inFlight).toBe(false);
    expect(result.current.context?.pct).toBe(55);
  });
});
