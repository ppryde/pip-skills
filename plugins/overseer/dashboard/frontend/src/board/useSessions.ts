/**
 * Shared census-session poll (WF-029 chunk 1). Lifted out of the old
 * SessionsPanel (retiring — chunk 7) so TopBar's "N questing" pill and the
 * new PartyColumn/PartyOverlay all read the SAME poll at the same instant
 * (see the card's Decisions: "PartyColumn and TopBar's pill must agree at
 * every instant"). ClaimControl keeps its own independent poll — untouched,
 * out of scope.
 *
 * Behaviour mirrors the old panel exactly: fetch on mount, poll every 5s,
 * swallow errors silently (leaving the last good state on screen), and
 * guard against setState after unmount. Sessions are recency-sorted here
 * (most recently active first) so every consumer gets the same order for
 * free.
 */
import { useEffect, useRef, useState } from "react";
import { getSessions } from "../api/client";
import type { SessionSummary } from "../api/types";

const POLL_INTERVAL_MS = 5000;

export interface UseSessionsResult {
  sessions: SessionSummary[];
}

// updated_at arrives as an epoch number, an ISO string, or null — normalise
// to a comparable epoch (null/unparseable sort last).
function activity(value: SessionSummary["updated_at"]): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

export function useSessions(): UseSessionsResult {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const isMountedRef = useRef(true);

  const loadSessions = async () => {
    try {
      const res = await getSessions();
      if (isMountedRef.current) {
        setSessions(res.sessions);
      }
    } catch {
      // Silently swallow errors — leave existing state untouched
    }
  };

  // Mount fetch. The ref is re-armed on every effect run — under
  // StrictMode's dev double-mount the first cleanup would otherwise leave
  // it permanently false and consumers stuck on the empty state.
  useEffect(() => {
    isMountedRef.current = true;
    void loadSessions();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Poll every 5 seconds.
  useEffect(() => {
    const intervalId = setInterval(() => {
      void loadSessions();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, []);

  // Most recently active first — sorted at render so the polled state stays
  // exactly what the API returned.
  const ordered = [...sessions].sort(
    (a, b) => activity(b.updated_at) - activity(a.updated_at)
  );

  return { sessions: ordered };
}
