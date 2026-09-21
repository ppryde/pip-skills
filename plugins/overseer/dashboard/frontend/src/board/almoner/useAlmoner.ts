/**
 * Almoner data hooks (the optional inflow-triage page).
 *
 * `useAlmonerStatus` — one fetch on mount; tells App whether to offer the
 * page at all. `useAlmonerDigest` — the digest, fetched ONLY when asked.
 *
 * Deliberately unlike `useChronicle`: there is no poll and no auto-refresh.
 * Chronicle reads local transcript files and can afford a 30s timer; a
 * digest is several remote round trips, and on the connector-backed
 * transports a headless agent run behind each one. "No schedule — refresh is
 * manual, by design" is a stated non-goal of the plugin, not an omission.
 *
 * Follows the dashboard's data-hook conventions otherwise: errors are
 * captured rather than thrown, and previous data is held while a refetch is
 * in flight so the page dims instead of flashing a skeleton.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getAlmonerDigest, getAlmonerStatus } from "../../api/client";
import type { AlmonerDigest, AlmonerStatus } from "../../api/types";

export function useAlmonerStatus(): AlmonerStatus | null {
  const [status, setStatus] = useState<AlmonerStatus | null>(null);
  useEffect(() => {
    let mounted = true;
    // As in `useChronicleStatus`: a synchronous throw from a partially-mocked
    // client module becomes a rejection this chain already handles, rather
    // than an error escaping the effect.
    Promise.resolve()
      .then(() => getAlmonerStatus())
      .then((res) => {
        if (mounted) setStatus(res);
      })
      .catch(() => {
        if (mounted) setStatus({ installed: false });
      });
    return () => {
      mounted = false;
    };
  }, []);
  return status;
}

export interface AlmonerDigestState {
  digest: AlmonerDigest | null;
  loading: boolean;
  error: string | null;
  /** Null until the first refresh — the page opens empty and says so, rather
   * than spending a headless agent run nobody asked for. */
  refreshedAt: number | null;
  refresh: () => void;
}

export function useAlmonerDigest(
  query: { hours?: number; context?: string } = {}
): AlmonerDigestState {
  const [digest, setDigest] = useState<AlmonerDigest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);

  // A refresh in flight is abandoned if another is asked for: these are slow
  // enough that a double-click would otherwise race two agent runs, and the
  // loser could land last and overwrite the newer answer.
  const inFlight = useRef<AbortController | null>(null);
  const { hours, context } = query;

  const refresh = useCallback(() => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setLoading(true);
    setError(null);
    Promise.resolve()
      .then(() => getAlmonerDigest({ hours, context }, { signal: controller.signal }))
      .then((res) => {
        if (controller.signal.aborted) return;
        // The backend answers 200 even when the almoner CLI itself failed
        // (timeout, non-zero exit, bad JSON) — soft-degrading is the whole
        // point of the sibling-plugin pattern, so this is not a thrown
        // rejection. `error` is how it still reaches the SAME failure path a
        // network error would: rendering it as "nothing needs you" would be
        // the silently-short digest the design forbids.
        if (res.error) {
          setError(res.error);
          return;
        }
        setDigest(res);
        setRefreshedAt(Date.now());
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Could not reach the almoner");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
  }, [hours, context]);

  useEffect(() => () => inFlight.current?.abort(), []);

  return { digest, loading, error, refreshedAt, refresh };
}
