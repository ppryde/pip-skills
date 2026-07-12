/**
 * Board state container.
 *
 * `mutate()` is the SINGLE entrypoint every mutation (drag in C4, drawer
 * controls in C5/C6) must route through — see wf005-context.md "Global
 * constraints": no control may call the api client + setState directly.
 * It owns a monotonic request counter + in-flight lock so that out-of-order
 * responses (a slow earlier request resolving after a faster later one) are
 * dropped rather than clobbering fresher state.
 *
 * This chunk (C3) performs no mutations itself — it only builds this
 * scaffold for later chunks to call.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getBoard } from "../api/client";
import type { Board, BoardResponse, Context, Limits } from "../api/types";

/** Background poll cadence — paused while a drag or mutation is in flight. */
const POLL_INTERVAL_MS = 5000;

export interface UseBoardResult {
  board: Board | null;
  context: Context | null;
  limits: Limits;
  loading: boolean;
  error: string | null;
  inFlight: boolean;
  refresh: () => Promise<void>;
  mutate: (fn: () => Promise<BoardResponse>) => Promise<void>;
  /** Board wires this from dnd-kit's onDragStart/onDragEnd/onDragCancel so
   *  the poll loop pauses for the duration of a drag. Ref-backed (not
   *  state) so the setInterval tick always reads the latest value without
   *  needing to be re-created every render. */
  setDragActive: (active: boolean) => void;
}

export function useBoard(): UseBoardResult {
  const [board, setBoard] = useState<Board | null>(null);
  const [context, setContext] = useState<Context | null>(null);
  const [limits, setLimits] = useState<Limits>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState(false);

  // Monotonic counter: each request gets an issued id; a response is only
  // applied if its id is still the latest issued when it resolves.
  const requestIdRef = useRef(0);

  // Mirrors of `inFlight` / drag state for the setInterval poll tick, which
  // closes over refs (not state) so it always sees the current value without
  // needing the effect that owns the interval to re-run every render.
  const inFlightRef = useRef(false);
  const dragActiveRef = useRef(false);

  const setDragActive = useCallback((active: boolean) => {
    dragActiveRef.current = active;
  }, []);

  const applyResponse = useCallback((res: BoardResponse) => {
    setBoard(res.board);
    setContext(res.context);
    setLimits(res.limits);
  }, []);

  // `silent` is for the background poll: it still goes through the SAME
  // epoch/staleness guard (`requestIdRef`) and `applyResponse` as a manual
  // refresh, but it must never flip `loading` (that drives the TopBar
  // "Refreshing…" button) or `error` (that renders a visible banner in
  // App.tsx) — a poll tick is invisible unless it succeeds, in which case
  // the board just quietly updates. A rejected poll leaves the last good
  // board on screen and surfaces nothing.
  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      const silent = opts?.silent ?? false;
      const id = ++requestIdRef.current;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await getBoard();
        if (id !== requestIdRef.current) return; // stale — a newer load/refresh/mutate won
        applyResponse(res);
      } catch (e) {
        if (id !== requestIdRef.current) return;
        if (!silent) {
          setError(e instanceof Error ? e.message : String(e));
        }
        // silent: swallow — no error state, no console noise, last good
        // board data (already applied from a prior response) stays put.
      } finally {
        if (id === requestIdRef.current && !silent) setLoading(false);
      }
    },
    [applyResponse]
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = useCallback(async () => {
    await load();
  }, [load]);

  const mutate = useCallback(
    async (fn: () => Promise<BoardResponse>) => {
      const id = ++requestIdRef.current;
      inFlightRef.current = true;
      setInFlight(true);
      try {
        const res = await fn();
        // Apply only if still the latest issued request (drop stale/out-of-order).
        if (id === requestIdRef.current) {
          applyResponse(res);
          setError(null);
        }
      } catch (e) {
        if (id === requestIdRef.current) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        // Clear the lock UNCONDITIONALLY. `requestIdRef` is shared with
        // load()/refresh(), which bump it without touching `inFlight`; gating
        // the clear on `id === requestIdRef.current` would strand the lock
        // (and disable drags forever) whenever a refresh races an in-flight
        // mutation. Staleness only governs whether we APPLY the response.
        inFlightRef.current = false;
        setInFlight(false);
      }
    },
    [applyResponse]
  );

  // Background poll: every 5s, silently refresh unless a mutation or a drag
  // is in flight. Both gates are read from refs at tick time so the interval
  // itself never needs to be torn down/recreated when inFlight/drag toggle.
  useEffect(() => {
    const intervalId = setInterval(() => {
      if (inFlightRef.current || dragActiveRef.current) return;
      void load({ silent: true });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [load]);

  return {
    board,
    context,
    limits,
    loading,
    error,
    inFlight,
    refresh,
    mutate,
    setDragActive,
  };
}
