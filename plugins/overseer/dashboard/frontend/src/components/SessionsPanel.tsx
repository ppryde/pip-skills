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

  // Every cell renders even when its datum is absent (empty spans) so the
  // shared row grid keeps columns aligned across rows — see styles.css.
  return (
    <div className="sessions-panel" role="region" aria-label="Active sessions">
      {sessions.length === 0 && (
        <div className="sessions-panel__empty">No active sessions</div>
      )}

      {sessions.map((session) => (
        <div
          key={session.id}
          className={`sessions-panel__row${
            session.stale ? " sessions-panel__row--stale" : ""
          }`}
        >
          <span className="sessions-panel__name" title={session.session_name || session.id}>
            {session.session_name || session.id}
          </span>

          <span className="sessions-panel__model">
            {session.model && (
              <span className="sessions-panel__pill">{session.model}</span>
            )}
          </span>

          <span className="sessions-panel__ctx">
            {session.pct === undefined ? "— unknown" : `${session.pct}%`}
          </span>

          <span
            className="sessions-panel__worktree"
            title={session.worktree_cwd || undefined}
          >
            {session.worktree_cwd && session.worktree_cwd.split("/").pop()}
          </span>

          <span className="sessions-panel__pr">
            {session.pr && (
              <span className="sessions-panel__pill">
                PR
                {session.pr.number !== undefined ? ` #${session.pr.number}` : ""}
                {session.pr.review_state ? ` · ${session.pr.review_state}` : ""}
              </span>
            )}
          </span>

          <span className="sessions-panel__status">
            <span className="sessions-panel__status-dot" aria-hidden="true" />
            {session.stale ? "stale" : "live"}
          </span>
        </div>
      ))}
    </div>
  );
}

export default SessionsPanel;
