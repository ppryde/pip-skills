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

/** A promise whose resolve/reject are exposed so the test drives ordering explicitly. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
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

  it("REGRESSION: a poll tick during a manual refresh must not strand loading — refresh settles loading=false and applies its data", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.loading).toBe(false);
    const callsAfterMount = mockedGetBoard.mock.calls.length;

    // Manual refresh whose response we hold open across a poll boundary.
    const manual = deferred<BoardResponse>();
    mockedGetBoard.mockReturnValueOnce(manual.promise);
    let refreshDone: Promise<void>;
    act(() => {
      refreshDone = result.current.refresh();
    });
    expect(result.current.loading).toBe(true);

    // 5s elapses mid-refresh — the tick must NOT fire a competing getBoard
    // (which would bump the shared epoch and mark the manual response stale).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockedGetBoard.mock.calls.length).toBe(callsAfterMount + 1);

    // Manual refresh resolves: loading MUST clear (the bug left it stuck
    // true forever — disabled "Refreshing…" button with no recovery).
    await act(async () => {
      manual.resolve(boardResponse(33));
      await refreshDone;
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.context?.pct).toBe(33);
  });

  it("REGRESSION: a manual refresh REJECTING across a poll boundary still surfaces its error and clears loading", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const manual = deferred<BoardResponse>();
    mockedGetBoard.mockReturnValueOnce(manual.promise);
    let refreshDone: Promise<void>;
    act(() => {
      refreshDone = result.current.refresh();
    });
    expect(result.current.loading).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    // Manual failure MUST surface — polls swallow errors, manual never does.
    await act(async () => {
      manual.reject(new Error("board fetch failed"));
      await refreshDone;
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe("board fetch failed");
  });

  it("a manual refresh made STALE by a racing mutation still clears loading and surfaces its rejection", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Manual refresh in flight...
    const manual = deferred<BoardResponse>();
    mockedGetBoard.mockReturnValueOnce(manual.promise);
    let refreshDone: Promise<void>;
    act(() => {
      refreshDone = result.current.refresh();
    });
    expect(result.current.loading).toBe(true);

    // ...then a mutation completes, bumping the shared epoch past the
    // refresh's id — the refresh's RESPONSE is now stale, but the flags it
    // owns (loading/error) must still settle.
    await act(async () => {
      await result.current.mutate(() => Promise.resolve(boardResponse(20)));
    });
    expect(result.current.context?.pct).toBe(20);

    await act(async () => {
      manual.reject(new Error("late failure"));
      await refreshDone;
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe("late failure");
    // The mutation's fresher data was not clobbered (apply stays epoch-guarded).
    expect(result.current.context?.pct).toBe(20);
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
