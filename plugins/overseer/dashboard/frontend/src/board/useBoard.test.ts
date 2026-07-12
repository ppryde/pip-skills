import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

describe("useBoard background polling (5s, paused during drag/mutation)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls getBoard every 5s: one extra call at 5s, three extra by 15s", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    renderHook(() => useBoard());

    // Mount fetch fires immediately (real useEffect, no timer involved).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(2); // +1 poll tick

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000); // total elapsed: 15s
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(4); // +3 poll ticks total
  });

  it("skips the poll tick while a mutation is in flight, resumes once it clears", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);

    const mut = deferred<BoardResponse>();
    act(() => {
      void result.current.mutate(() => mut.promise);
    });
    expect(result.current.inFlight).toBe(true);

    // A tick lands while the mutation is still in flight — gated, no call.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);

    // Mutation resolves, lock clears.
    await act(async () => {
      mut.resolve(boardResponse(20));
    });
    expect(result.current.inFlight).toBe(false);

    // Next tick polls normally again.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(2);
  });

  it("skips the poll tick while a drag is active, resumes once setDragActive(false)", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setDragActive(true);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1); // gated — no poll call

    act(() => {
      result.current.setDragActive(false);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(2); // resumed
  });

  it("clears the poll timer on unmount — no further calls after advancing", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { unmount } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);

    unmount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    // Unmounted before any poll tick fired — still just the mount fetch.
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);
  });

  it("a rejected poll leaves the last good board intact and surfaces nothing", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));
    mockedGetBoard.mockRejectedValueOnce(new Error("network blip"));

    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    const { result } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.context?.pct).toBe(10);
    expect(result.current.error).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    // Last good board data is untouched, and the failure was NOT surfaced
    // as a visible error (that's the manual-refresh path, not polling).
    expect(result.current.context?.pct).toBe(10);
    expect(result.current.error).toBeNull();
    expect(consoleError).not.toHaveBeenCalled();

    consoleError.mockRestore();
  });
});
