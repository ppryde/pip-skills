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

  // Mount fetch
  useEffect(() => {
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

  return (
    <div className="sessions-panel" role="region" aria-label="Active sessions">
      {sessions.map((session) => (
        <div key={session.id} className="sessions-panel__row">
          <span className="sessions-panel__name">
            {session.session_name || session.id}
          </span>

          {session.model && (
            <span className="sessions-panel__pill">{session.model}</span>
          )}

          <span className="sessions-panel__ctx">
            {session.pct === undefined ? "— unknown" : `${session.pct}%`}
          </span>

          {session.worktree_cwd && (
            <span className="sessions-panel__worktree">
              {session.worktree_cwd.split("/").pop()}
            </span>
          )}

          {session.pr && (
            <span className="sessions-panel__pill">
              PR{session.pr.number !== undefined ? ` #${session.pr.number}` : ""}
              {session.pr.review_state ? ` · ${session.pr.review_state}` : ""}
            </span>
          )}

          <span className="sessions-panel__status">
            {session.stale ? "stale" : "live"}
          </span>
        </div>
      ))}
    </div>
  );
}

export default SessionsPanel;
