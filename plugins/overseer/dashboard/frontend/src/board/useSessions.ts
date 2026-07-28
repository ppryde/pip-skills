/**
 * Shared census-session poll (WF-029 chunk 1). Lifted out of the retired
 * dark sessions dropdown (chunk 7) so TopBar's "N questing" pill and the
 * PartyColumn/PartyOverlay all read the SAME poll at the same instant
 * (see the card's Decisions: "PartyColumn and TopBar's pill must agree at
 * every instant"). ClaimControl keeps its own independent poll — untouched,
 * out of scope.
 *
 * Behaviour mirrors the old dropdown exactly: fetch on mount, poll every
 * 5s, swallow errors silently (leaving the last good state on screen), and
 * guard against setState after unmount. Sessions are recency-sorted here
 * (most recently active first) so every consumer gets the same order for
 * free.
 *
 * `root` (WF-031) mirrors `useBoard`'s own `root` param exactly: the
 * currently-selected repo's root path, or `null` for the dashboard's own
 * launch root. `setActiveRoot(root)` fires synchronously at the start of
 * the same effect that issues the mount/root-change fetch — by the time
 * `getSessions()` builds its URL, `api/client`'s module-level root is
 * already correct, so Party re-scopes to the newly-selected repo exactly
 * when the board does (no cross-effect race).
 *
 * `enabled` (task 10, mirroring `useBoard`'s own gate — WF-032) hard-gates
 * BOTH the mount/root-change fetch AND the poll: App.tsx passes `false` for
 * an "unbegun" repo (`has_board: false`), which 400s the backend's
 * `/api/sessions?root=...` exactly like it 400s `/api/board` — see
 * `useBoard`'s doc comment for the identical rationale.
 */
import { useEffect, useRef, useState } from "react";
import { getSessions, setActiveRoot } from "../api/client";
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

export function useSessions(
  root: string | null = null,
  enabled: boolean = true
): UseSessionsResult {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const isMountedRef = useRef(true);
  // Mirrors `enabled` for the poll tick (same rationale as `useBoard`'s
  // `enabledRef`): the interval effect below has an empty dep array so it
  // never tears down/recreates, but a toggle of `enabled` alone must still
  // be visible to it at tick time.
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

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

  // Mount fetch, AND re-fires whenever the selected repo root (or `enabled`)
  // changes — setting the module-level active root FIRST (synchronously,
  // before `loadSessions()`) so this fetch targets the newly-selected repo.
  // The ref is re-armed on every effect run — under StrictMode's dev
  // double-mount the first cleanup would otherwise leave it permanently
  // false and consumers stuck on the empty state. `enabled: false` is a hard
  // skip: no `setActiveRoot`, no fetch — an unbegun root must never reach
  // `getSessions()` (it 400s the backend exactly like `/api/board` does).
  useEffect(() => {
    if (!enabled) return;
    isMountedRef.current = true;
    setActiveRoot(root);
    void loadSessions();

    return () => {
      isMountedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, enabled]);

  // Poll every 5 seconds, skipping ticks while disabled.
  useEffect(() => {
    const intervalId = setInterval(() => {
      if (!enabledRef.current) return;
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
