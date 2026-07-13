import { useEffect, useRef, useState } from "react";
import { getSessions } from "../api/client";
import type { SessionSummary } from "../api/types";

const POLL_INTERVAL_MS = 5000;

/**
 * SessionsPanel displays a list of active sessions from the census store.
 * Fetches on mount and polls every 5 seconds, silently swallowing errors
 * to avoid disrupting the UI. Cleans up on unmount to prevent setState
 * from resolving in-flight fetches after the component has unmounted.
 */
function SessionsPanel() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const isMountedRef = useRef(true);

  // Load sessions, swallowing errors silently
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
  // it permanently false and the panel stuck on the empty state.
  useEffect(() => {
    isMountedRef.current = true;
    void loadSessions();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Poll every 5 seconds
  useEffect(() => {
    const intervalId = setInterval(() => {
      void loadSessions();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, []);

  // updated_at arrives as an epoch number, an ISO string, or null —
  // normalise to a comparable epoch (null/unparseable sort last).
  const activity = (value: SessionSummary["updated_at"]): number => {
    if (typeof value === "number") return value;
    if (typeof value === "string") {
      const parsed = Date.parse(value);
      return Number.isNaN(parsed) ? 0 : parsed;
    }
    return 0;
  };

  // Most recently active first — sorted at render so the polled state stays
  // exactly what the API returned.
  const ordered = [...sessions].sort(
    (a, b) => activity(b.updated_at) - activity(a.updated_at)
  );

  // Two-line rows: line 1 gives the name the full panel width (plus the
  // live/stale status at the right edge); line 2 carries the labels.
  return (
    <div className="sessions-panel" role="region" aria-label="Active sessions">
      {ordered.length === 0 && (
        <div className="sessions-panel__empty">No active sessions</div>
      )}

      {ordered.map((session) => (
        <div
          key={session.id}
          className={`sessions-panel__row${
            session.stale ? " sessions-panel__row--stale" : ""
          }`}
        >
          <div className="sessions-panel__header">
            <span
              className="sessions-panel__name"
              title={session.session_name || session.id}
            >
              {session.session_name || session.id}
            </span>

            <span className="sessions-panel__status">
              <span className="sessions-panel__status-dot" aria-hidden="true" />
              {session.stale ? "stale" : "live"}
            </span>
          </div>

          <div className="sessions-panel__meta">
            {session.model && (
              <span className="sessions-panel__pill">{session.model}</span>
            )}

            <span className="sessions-panel__ctx">
              {session.pct === undefined ? "— unknown" : `${session.pct}%`}
            </span>

            {session.worktree_cwd && (
              <span
                className="sessions-panel__worktree"
                title={session.worktree_cwd}
              >
                {session.worktree_cwd.split("/").pop()}
              </span>
            )}

            {session.pr && (
              <span className="sessions-panel__pill">
                PR
                {session.pr.number !== undefined ? ` #${session.pr.number}` : ""}
                {session.pr.review_state ? ` · ${session.pr.review_state}` : ""}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export default SessionsPanel;
