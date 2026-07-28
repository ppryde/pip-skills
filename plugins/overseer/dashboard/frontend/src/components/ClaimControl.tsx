import { useEffect, useState } from "react";
import { claimCard, getSessions, unclaimCard } from "../api/client";
import type { SessionSummary } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";

const POLL_INTERVAL_MS = 5000;

export interface ClaimControlProps {
  cardId: string;
  claimedBy: string | null | undefined;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Called after a mutation settles — the drawer wires this to its
   * counter-guarded `getCard` refetch (see wf005-c6-brief.md). */
  onMutated?: () => void;
}

/**
 * "Assign to session" drawer control (design spec §5). The board/card-detail
 * payload only carries `claimed_by` (a bare census session_id) — it has no
 * session data of its own, so this component fetches+polls `getSessions()`
 * itself, a self-contained fetch pattern deliberately independent of the
 * shared useSessions() poll (see that hook's doc comment). Unassigned: a select of
 * LIVE (non-stale) sessions plus an Assign button. Claimed: the holder's
 * label (session_name if that session is still present in the live poll,
 * else the raw session id) dimmed when the holder has gone stale, plus an
 * Unassign button. Both actions route through `useBoard().mutate` — this
 * component never calls the api client + setState itself.
 */
function ClaimControl({
  cardId,
  claimedBy,
  mutate,
  inFlight,
  onMutated,
}: ClaimControlProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await getSessions();
        if (!cancelled) setSessions(res.sessions);
      } catch {
        // Silently swallow — leaves prior state put.
      }
    }

    void load();
    const intervalId = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, []);

  async function handleAssign() {
    if (!selected) return;
    await mutate(() => claimCard(cardId, selected));
    setSelected("");
    onMutated?.();
  }

  async function handleUnassign() {
    await mutate(() => unclaimCard(cardId));
    onMutated?.();
  }

  if (claimedBy) {
    const holder = sessions.find((s) => s.id === claimedBy);
    const label = holder?.session_name || claimedBy;
    return (
      <div className="claim-control">
        <span
          className={`claim-control__holder${
            holder?.stale ? " claim-control__holder--stale" : ""
          }`}
          title={claimedBy}
        >
          claimed by {label}
        </span>
        <button
          type="button"
          onClick={() => void handleUnassign()}
          disabled={inFlight}
        >
          Unassign
        </button>
      </div>
    );
  }

  const liveSessions = sessions.filter((s) => !s.stale);

  return (
    <div className="claim-control">
      <select
        aria-label="Assign to session"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        disabled={inFlight}
      >
        <option value="">— assign to session —</option>
        {liveSessions.map((s) => (
          <option key={s.id} value={s.id}>
            {s.session_name || s.id}
            {s.model ? ` (${s.model})` : ""}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => void handleAssign()}
        disabled={inFlight || !selected}
      >
        Assign
      </button>
    </div>
  );
}

export default ClaimControl;
