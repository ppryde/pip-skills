/**
 * Chronicle data hooks (the optional session-telemetry page).
 *
 * `useChronicleStatus` — one fetch on mount; tells App whether to offer the
 * page at all. `useChronicle` — the page's summary + session list, re-fetched
 * whenever the selected root / time window / scope / branch changes and
 * polled every 30s while enabled. `useChronicleSync` — the Sync action, plus
 * the quiet auto-sync the page runs while it shows: chronicle is pull only
 * (no hooks, by design), so the dashboard is what keeps the store current.
 * `useChronicleSession` — one session's detail for the drawer.
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
  syncChronicle,
} from "../../api/client";
import type {
  ChronicleQuery,
  ChronicleSession,
  ChronicleSessionDetail,
  ChronicleStatus,
  ChronicleSummary,
  ChronicleSyncResponse,
} from "../../api/types";

const POLL_INTERVAL_MS = 30_000;
/** How often the open Chronicle page asks the backend to reconcile the
 * store with the transcripts on disk. A no-change sync is a directory walk
 * (per-file cursors), so a minute is cheap; turns land at roughly that
 * cadence anyway. */
export const AUTO_SYNC_INTERVAL_MS = 60_000;
/** Auto-syncs closer together than this are skipped — filter changes re-run
 * the effect that schedules them, and a sync per click is wasted work. */
const AUTO_SYNC_MIN_GAP_MS = 15_000;

/** Whether the page is in the foreground (Page Visibility API). Timers
 * that fetch or sync pause while a tab is hidden — a background tab has no
 * one to show anything to — and the callers catch up once on return. */
export function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(() => typeof document === "undefined" || !document.hidden);
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

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
  // Polls only while enabled AND in the foreground; a hidden tab's timer
  // ticks are skipped, and coming back to the foreground reloads once.
  const visible = useDocumentVisible();
  const active = enabled && visible;
  const activeRef = useRef(active);
  activeRef.current = active;
  const { days, scope, branch } = query;

  const load = useCallback(async () => {
    setActiveRoot(root);
    setLoading(true);
    try {
      const [sum, list] = await Promise.all([
        getChronicleSummary({ days, scope, branch }),
        getChronicleSessions({ days, scope, branch }),
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
  }, [root, days, scope, branch]);

  useEffect(() => {
    mountedRef.current = true;
    if (active) void load();
    return () => {
      mountedRef.current = false;
    };
  }, [load, active]);

  useEffect(() => {
    const id = setInterval(() => {
      if (activeRef.current) void load();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  return { summary, sessions, loading, error, refresh: load };
}

export function formatSyncSummary(res: ChronicleSyncResponse): string {
  if (res.changed === 0) return `Synced — nothing new across ${res.scanned} files.`;
  const noun = res.changed === 1 ? "session" : "sessions";
  return `Synced — ${res.changed} ${noun} updated (${res.lines} new lines).`;
}

export interface UseChronicleSyncResult {
  /** Ask the backend to reconcile chronicle's store with the transcripts on
   * disk, then re-read through `refresh`. The button's path: shows
   * "Syncing…", always leaves a note. */
  sync: () => Promise<void>;
  /** The same reconcile, unattended: no busy state, a note only when
   * something actually changed, failures swallowed (the next tick retries),
   * and skipped entirely when one is in flight or ran moments ago. */
  syncQuietly: () => Promise<void>;
  syncing: boolean;
  /** One line on the last sync's outcome (or failure); null before the
   * first. */
  note: string | null;
}

/** The "Sync" action, split from `useChronicle` because its button lives in
 * the top bar while the data lives with the page — App owns both and hands
 * each its half. `refresh` is the `useChronicle` result's. `enabled` runs
 * the quiet auto-sync on a timer while true AND the page is in the
 * foreground — a hidden tab syncs nothing, and catches up once on return. */
export function useChronicleSync(refresh: () => Promise<void>, enabled = false): UseChronicleSyncResult {
  const [syncing, setSyncing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const inFlightRef = useRef(false);
  const lastAutoRef = useRef(0);
  const visible = useDocumentVisible();
  const active = enabled && visible;

  const sync = useCallback(async () => {
    inFlightRef.current = true;
    setSyncing(true);
    setNote(null);
    try {
      const res = await syncChronicle();
      setNote(formatSyncSummary(res));
      await refresh();
    } catch (err) {
      setNote(`Sync failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      inFlightRef.current = false;
      lastAutoRef.current = Date.now();
      setSyncing(false);
    }
  }, [refresh]);

  const syncQuietly = useCallback(async () => {
    if (inFlightRef.current || Date.now() - lastAutoRef.current < AUTO_SYNC_MIN_GAP_MS) return;
    inFlightRef.current = true;
    try {
      // quiet: a tokened dashboard with no token in this browser must not
      // pop the token prompt on a timer — the manual Sync button does that.
      const res = await syncChronicle({ quiet: true });
      if (res.changed > 0) {
        setNote(formatSyncSummary(res));
        await refresh();
      }
    } catch {
      // Unattended: say nothing, the next tick tries again.
    } finally {
      inFlightRef.current = false;
      lastAutoRef.current = Date.now();
    }
  }, [refresh]);

  useEffect(() => {
    if (!active) return;
    void syncQuietly();
    const id = setInterval(() => void syncQuietly(), AUTO_SYNC_INTERVAL_MS);
    return () => clearInterval(id);
  }, [active, syncQuietly]);

  return { sync, syncQuietly, syncing, note };
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
