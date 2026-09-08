import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

vi.mock("../api/client", () => ({
  getBoard: vi.fn(),
  setActiveRoot: vi.fn(),
}));

import { getBoard, setActiveRoot } from "../api/client";
import { useBoard } from "./useBoard";

function boardResponse(pct: number): BoardResponse {
  return {
    board: { project: "p", cards: [], sprints: [], quarantined: [], label_colors: {} },
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

describe("useBoard.mutate() rethrow option (Task 10 fix-up)", () => {
  it("default (no opts) swallows a rejection: sets the global error, resolves (does not reject), clears inFlight", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      // No throw expected — mutate() must resolve normally even though
      // fn() rejected, exactly as before this option existed.
      await result.current.mutate(() => Promise.reject(new Error("boom")));
    });

    expect(result.current.error).toBe("boom");
    expect(result.current.inFlight).toBe(false);
  });

  it("rethrow: false behaves identically to the default (explicit opt-out is a no-op)", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.mutate(
        () => Promise.reject(new Error("boom")),
        { rethrow: false }
      );
    });

    expect(result.current.error).toBe("boom");
    expect(result.current.inFlight).toBe(false);
  });

  it("rethrow: true propagates the rejection to the caller AND does NOT set the global error state", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutate(
          () => Promise.reject(new Error("boom")),
          { rethrow: true }
        );
      } catch (e) {
        caught = e;
      }
    });

    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("boom");
    // The caller owns error display for a rethrown failure — no
    // double-surfacing in the global banner too.
    expect(result.current.error).toBeNull();
  });

  it("rethrow: true still clears the in-flight lock on rejection (finally runs regardless)", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current
        .mutate(() => Promise.reject(new Error("boom")), { rethrow: true })
        .catch(() => {});
    });

    expect(result.current.inFlight).toBe(false);
  });

  it("rethrow: true leaves the success path unchanged — applies the returned board and clears error", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.mutate(() => Promise.resolve(boardResponse(42)), {
        rethrow: true,
      });
    });

    expect(result.current.context?.pct).toBe(42);
    expect(result.current.error).toBeNull();
    expect(result.current.inFlight).toBe(false);
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

describe("useBoard(root) — WF-030 repo selector threading", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("defaults to root=null (setActiveRoot(null)) when no root arg is given", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValueOnce(boardResponse(10));
    const mockedSetActiveRoot = vi.mocked(setActiveRoot);

    renderHook(() => useBoard());
    await waitFor(() => expect(mockedGetBoard).toHaveBeenCalledTimes(1));

    expect(mockedSetActiveRoot).toHaveBeenCalledWith(null);
  });

  it("calls setActiveRoot(root) BEFORE fetching, on mount", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    const mockedSetActiveRoot = vi.mocked(setActiveRoot);
    const calls: string[] = [];
    mockedSetActiveRoot.mockImplementation(() => calls.push("setActiveRoot"));
    mockedGetBoard.mockImplementationOnce(async () => {
      calls.push("getBoard");
      return boardResponse(10);
    });

    renderHook(() => useBoard("/repo-a"));
    await waitFor(() => expect(calls).toContain("getBoard"));

    expect(calls).toEqual(["setActiveRoot", "getBoard"]);
    expect(mockedSetActiveRoot).toHaveBeenCalledWith("/repo-a");
  });

  it("re-fetches and re-applies setActiveRoot when the root prop changes", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));
    const mockedSetActiveRoot = vi.mocked(setActiveRoot);

    const { rerender } = renderHook(({ root }) => useBoard(root), {
      initialProps: { root: "/repo-a" as string | null },
    });
    await waitFor(() => expect(mockedGetBoard).toHaveBeenCalledTimes(1));
    expect(mockedSetActiveRoot).toHaveBeenLastCalledWith("/repo-a");

    rerender({ root: "/repo-b" });
    await waitFor(() => expect(mockedGetBoard).toHaveBeenCalledTimes(2));
    expect(mockedSetActiveRoot).toHaveBeenLastCalledWith("/repo-b");
  });
});

describe("useBoard(root, enabled) — WF-032 unbegun-repo fetch gate", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("enabled: false skips the mount fetch entirely — never calls setActiveRoot or getBoard", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    const mockedSetActiveRoot = vi.mocked(setActiveRoot);

    renderHook(() => useBoard("/unbegun-repo", false));

    // Give any stray microtask a chance to fire, then assert nothing did.
    await new Promise((r) => setTimeout(r, 0));

    expect(mockedGetBoard).not.toHaveBeenCalled();
    expect(mockedSetActiveRoot).not.toHaveBeenCalled();
  });

  it("toggling enabled from false to true fires the fetch", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));
    const mockedSetActiveRoot = vi.mocked(setActiveRoot);

    const { rerender } = renderHook(
      ({ enabled }) => useBoard("/repo-a", enabled),
      { initialProps: { enabled: false } }
    );

    await new Promise((r) => setTimeout(r, 0));
    expect(mockedGetBoard).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() => expect(mockedGetBoard).toHaveBeenCalledTimes(1));
    expect(mockedSetActiveRoot).toHaveBeenLastCalledWith("/repo-a");
  });

  it("WF-047: disabling drops the previous repo's board and context, keeping the account limits", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { result, rerender } = renderHook(
      ({ root, enabled }: { root: string; enabled: boolean }) => useBoard(root, enabled),
      { initialProps: { root: "/repo-a", enabled: true } }
    );
    await waitFor(() => expect(result.current.board).not.toBeNull());
    const limits = result.current.limits;

    rerender({ root: "/unbegun", enabled: false });
    expect(result.current.board).toBeNull();
    expect(result.current.context).toBeNull();
    expect(result.current.limits).toBe(limits);
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);
  });

  it("WF-047: a switch between two begun repos drops the old board before the new fetch lands", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { result, rerender } = renderHook(
      ({ root }: { root: string }) => useBoard(root, true),
      { initialProps: { root: "/repo-a" } }
    );
    await waitFor(() => expect(result.current.board).not.toBeNull());

    // Never repo A's cards under repo B's header, however briefly.
    let pending: (r: ReturnType<typeof boardResponse>) => void = () => {};
    mockedGetBoard.mockImplementationOnce(() => new Promise((resolve) => { pending = resolve; }));
    rerender({ root: "/repo-b" });
    expect(result.current.board).toBeNull();
    pending(boardResponse(3));
    await waitFor(() => expect(result.current.board).not.toBeNull());
  });

  it("WF-047: the launch root resolving from null to its path is not a switch — no loading flash", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { result, rerender } = renderHook(
      ({ root }: { root: string | null }) => useBoard(root, true),
      { initialProps: { root: null as string | null } }
    );
    await waitFor(() => expect(result.current.board).not.toBeNull());
    const loaded = result.current.board;

    mockedGetBoard.mockImplementationOnce(() => new Promise(() => {}));
    rerender({ root: "/launch-root" });
    expect(result.current.board).toBe(loaded); // kept while the refetch is in flight
    expect(mockedGetBoard).toHaveBeenCalledTimes(2);
  });
});

/**
 * The retry budget (WF: "keeps retrying for ages"). The board used to poll a
 * dead server every 5s forever and show one undifferentiated red strip; a
 * refused dashboard token got exactly the same treatment even though no
 * number of identical retries could ever be accepted.
 */
describe("useBoard fetch-failure retry budget", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  /** An ApiError-shaped rejection: `classifyFailure` reads `status`. */
  function httpError(status: number, message: string) {
    return Object.assign(new Error(message), { status });
  }

  it("schedules a retry with the backoff wait after a retryable failure", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useBoard());
    await vi.waitFor(() => expect(result.current.failure).not.toBeNull());

    expect(result.current.failure).toMatchObject({
      kind: "retryable",
      retries: 1,
      retryInSeconds: 2,
    });
    expect(result.current.error).toBe("Failed to fetch");
  });

  it("stops after the budget, leaving no further attempt scheduled", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useBoard());
    await vi.waitFor(() => expect(result.current.failure).not.toBeNull());

    // Run out the whole 2+4+8+16+30 schedule.
    for (const wait of [2, 4, 8, 16, 30]) {
      await act(async () => {
        vi.advanceTimersByTime(wait * 1000);
        await Promise.resolve();
      });
    }

    await vi.waitFor(() =>
      expect(result.current.failure?.retryInSeconds).toBeNull()
    );
    expect(result.current.failure?.retries).toBe(5);
    // One initial attempt plus five retries, and then it stops for good.
    expect(mockedGetBoard).toHaveBeenCalledTimes(6);

    await act(async () => {
      vi.advanceTimersByTime(120_000);
      await Promise.resolve();
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(6);
  });

  it("never retries a refused dashboard token", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockRejectedValue(httpError(401, "missing or invalid dashboard token"));

    const { result } = renderHook(() => useBoard());
    await vi.waitFor(() => expect(result.current.failure).not.toBeNull());

    expect(result.current.failure).toMatchObject({
      kind: "auth",
      retries: 0,
      retryInSeconds: null,
    });

    await act(async () => {
      vi.advanceTimersByTime(120_000);
      await Promise.resolve();
    });
    // The single original attempt, and nothing after it — not even the 5s
    // background poll, which must not creep past a terminal failure.
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);
  });

  it("never retries a request the server rejected outright", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockRejectedValue(httpError(400, "unknown root"));

    const { result } = renderHook(() => useBoard());
    await vi.waitFor(() =>
      expect(result.current.failure).toMatchObject({ kind: "rejected", retryInSeconds: null })
    );

    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
    });
    expect(mockedGetBoard).toHaveBeenCalledTimes(1);
  });

  it("cancel() clears the banner and stops everything, poll included", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useBoard());
    await vi.waitFor(() => expect(result.current.failure).not.toBeNull());
    const callsAtCancel = mockedGetBoard.mock.calls.length;

    act(() => result.current.cancel());
    expect(result.current.failure).toBeNull();
    expect(result.current.error).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
    });
    // Neither the scheduled retry nor the background poll may take over the
    // hammering the person just asked to stop.
    expect(mockedGetBoard).toHaveBeenCalledTimes(callsAtCancel);
  });

  it("a success clears the failure and restores the budget", async () => {
    const mockedGetBoard = vi.mocked(getBoard);
    mockedGetBoard.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    mockedGetBoard.mockResolvedValue(boardResponse(10));

    const { result } = renderHook(() => useBoard());
    await vi.waitFor(() => expect(result.current.failure).not.toBeNull());

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });

    await vi.waitFor(() => expect(result.current.failure).toBeNull());
    expect(result.current.error).toBeNull();
  });
});
