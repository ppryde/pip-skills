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
import { useVisibleInterval } from "../useDocumentVisible";

const POLL_INTERVAL_MS = 30_000;
/** How often the open Chronicle page asks the backend to reconcile the
 * store with the transcripts on disk. A no-change sync is a directory walk
 * (per-file cursors), so a minute is cheap; turns land at roughly that
 * cadence anyway. */
export const AUTO_SYNC_INTERVAL_MS = 60_000;
/** Auto-syncs closer together than this are skipped — filter changes re-run
 * the effect that schedules them, and a sync per click is wasted work. */
const AUTO_SYNC_MIN_GAP_MS = 15_000;

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
  // Every load takes a ticket; only the newest ticket's response lands. A
  // filter change racing a poll tick, or a slow old query finishing after a
  // fast new one, must not paint stale data over fresh (the same epoch
  // guard useBoard uses). Unmount just means no ticket is current.
  const requestIdRef = useRef(0);
  const { days, scope, branch } = query;

  const load = useCallback(async () => {
    const id = ++requestIdRef.current;
    setActiveRoot(root);
    setLoading(true);
    try {
      const [sum, list] = await Promise.all([
        getChronicleSummary({ days, scope, branch }),
        getChronicleSessions({ days, scope, branch }),
      ]);
      if (id !== requestIdRef.current) return;
      setSummary(sum);
      setSessions(list.sessions);
      setError(null);
    } catch (err) {
      if (id !== requestIdRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (id === requestIdRef.current) setLoading(false);
    }
  }, [root, days, scope, branch]);

  useEffect(() => {
    const ref = requestIdRef;
    return () => {
      ref.current += 1; // retire any in-flight response on unmount
    };
  }, []);

  // Loads on enable and on every filter change (`load` is new then) …
  useEffect(() => {
    if (enabled) void load();
  }, [load, enabled]);
  // … then every POLL_INTERVAL_MS while enabled and visible, with one
  // catch-up load when a hidden tab comes back; a hidden tab polls nothing.
  useVisibleInterval(() => void load(), POLL_INTERVAL_MS, enabled, { immediate: "on-return" });

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

  const sync = useCallback(async () => {
    // One sync at a time against one SQLite store: a click while the timed
    // sync is running just waits for its result.
    if (inFlightRef.current) return;
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
      // quiet: an unattended timer must never pop the token prompt. The sync
      // route is ungated today, so this is a guard against the gate ever
      // returning — a 401 here fails silently; the manual Sync button prompts.
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

  // Quiet sync on enable/show and every minute while enabled and visible;
  // the min-gap guard inside syncQuietly absorbs the immediate tick when a
  // sync just ran.
  useVisibleInterval(() => void syncQuietly(), AUTO_SYNC_INTERVAL_MS, enabled);

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
