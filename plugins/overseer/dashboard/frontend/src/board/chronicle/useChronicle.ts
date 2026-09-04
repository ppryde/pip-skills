/**
 * Chronicle data hooks (the optional session-telemetry page).
 *
 * `useChronicleStatus` — one fetch on mount; tells App whether to offer the
 * page at all. `useChronicle` — the page's summary + session list, re-fetched
 * whenever the selected root / time window / scope changes and polled every
 * 30s while enabled (sessions accrue turns at Stop-hook cadence, so a 5s poll
 * like `useSessions` would be wasted work). `useChronicleSession` — one
 * session's detail for the drawer.
 *
 * All three follow the dashboard's data-hook conventions: `setActiveRoot`
 * is called synchronously before the fetch (see `useSessions`), errors are
 * captured rather than thrown, and the previous data is held while a
 * refetch is in flight (no skeleton flash — `loading` lets the page dim).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getChronicleSession,
  getChronicleSessions,
  getChronicleStatus,
  getChronicleSummary,
  setActiveRoot,
} from "../../api/client";
import type {
  ChronicleQuery,
  ChronicleSession,
  ChronicleSessionDetail,
  ChronicleStatus,
  ChronicleSummary,
} from "../../api/types";

const POLL_INTERVAL_MS = 30_000;

export function useChronicleStatus(): ChronicleStatus | null {
  const [status, setStatus] = useState<ChronicleStatus | null>(null);
  useEffect(() => {
    let mounted = true;
    // `Promise.resolve().then(...)` turns a synchronous throw from the client
    // (e.g. a partially-mocked module in tests) into a rejection this chain
    // already handles, rather than an error escaping the effect.
    Promise.resolve()
      .then(() => getChronicleStatus())
      .then((res) => {
        if (mounted) setStatus(res);
      })
      .catch(() => {
        // Older backend without the route, or a fetch hiccup: treat as
        // "not installed" — the page simply isn't offered.
        if (mounted) setStatus({ installed: false, exists: false });
      });
    return () => {
      mounted = false;
    };
  }, []);
  return status;
}

export interface UseChronicleResult {
  summary: ChronicleSummary | null;
  sessions: ChronicleSession[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useChronicle(
  root: string | null,
  query: ChronicleQuery,
  enabled: boolean
): UseChronicleResult {
  const [summary, setSummary] = useState<ChronicleSummary | null>(null);
  const [sessions, setSessions] = useState<ChronicleSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const { days, scope } = query;

  const load = useCallback(async () => {
    setActiveRoot(root);
    setLoading(true);
    try {
      const [sum, list] = await Promise.all([
        getChronicleSummary({ days, scope }),
        getChronicleSessions({ days, scope }),
      ]);
      if (!mountedRef.current) return;
      setSummary(sum);
      setSessions(list.sessions);
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [root, days, scope]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) void load();
    return () => {
      mountedRef.current = false;
    };
  }, [load, enabled]);

  useEffect(() => {
    const id = setInterval(() => {
      if (enabledRef.current) void load();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  return { summary, sessions, loading, error, refresh: load };
}

export interface UseChronicleSessionResult {
  detail: ChronicleSessionDetail | null;
  loading: boolean;
  error: string | null;
}

export function useChronicleSession(id: string | null): UseChronicleSessionResult {
  const [detail, setDetail] = useState<ChronicleSessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id === null) {
      setDetail(null);
      setError(null);
      return;
    }
    let mounted = true;
    setLoading(true);
    Promise.resolve()
      .then(() => getChronicleSession(id))
      .then((res) => {
        if (!mounted) return;
        setDetail(res);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [id]);

  return { detail, loading, error };
}
