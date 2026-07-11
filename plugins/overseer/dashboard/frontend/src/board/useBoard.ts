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

export interface UseBoardResult {
  board: Board | null;
  context: Context | null;
  limits: Limits;
  loading: boolean;
  error: string | null;
  inFlight: boolean;
  refresh: () => Promise<void>;
  mutate: (fn: () => Promise<BoardResponse>) => Promise<void>;
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

  const applyResponse = useCallback((res: BoardResponse) => {
    setBoard(res.board);
    setContext(res.context);
    setLimits(res.limits);
  }, []);

  const load = useCallback(async () => {
    const id = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await getBoard();
      if (id !== requestIdRef.current) return; // stale — a newer load/refresh/mutate won
      applyResponse(res);
    } catch (e) {
      if (id !== requestIdRef.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (id === requestIdRef.current) setLoading(false);
    }
  }, [applyResponse]);

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
      setInFlight(true);
      try {
        const res = await fn();
        if (id !== requestIdRef.current) return; // stale/out-of-order — drop it
        applyResponse(res);
        setError(null);
      } catch (e) {
        if (id !== requestIdRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (id === requestIdRef.current) setInFlight(false);
      }
    },
    [applyResponse]
  );

  return { board, context, limits, loading, error, inFlight, refresh, mutate };
}
