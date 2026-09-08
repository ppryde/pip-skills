import { useEffect, useState } from "react";
import { Button } from "../ui";
import { MAX_RETRIES } from "../board/retry";
import type { FetchFailure } from "../board/useBoard";
import backpackIcon from "../assets/ui-icons/backpack.png";

/**
 * The fetch-failure state, in the guild's voice: the messenger to the server
 * has been waylaid. Shared by the board and the Chronicle page in place of a
 * bare red line.
 *
 * It now tells the truth about what is actually happening, which it did not
 * before. The old strip said "we'll keep sending riders until one makes it
 * through" and meant it — an unbounded 5s poll that never surfaced a result,
 * shown identically whether the server was restarting or the dashboard token
 * had been refused. Three states now, driven by `FetchFailure`:
 *
 * - RIDING: a retryable failure with budget left. Counts down to the next
 *   automatic attempt and says which of the five it will be.
 * - LOST: the budget is spent. No countdown, because nothing is coming.
 * - TURNED BACK: the gate refused the token (401/403), or the server rejected
 *   the request outright. Never retried — an identical request can only be
 *   refused identically — so the copy asks for the one thing that would help.
 *
 * A slim red-tinted torn-note strip with a compass whose NEEDLE turns — drawn
 * as SVG in the top bar's icon style so the needle is its own part (the
 * compass PNG is one flat image). The raw error stays as a quiet detail line,
 * so the whimsy never hides the fact. The "Send a rider" button carries the
 * pack's backpack — the rider's kit. Motion pauses under
 * prefers-reduced-motion, and stops entirely once nothing is riding.
 */
export interface WaylaidProps {
  /** The raw failure, verbatim ("Failed to fetch") — kept visible. */
  error: string;
  /** Classification and retry budget. Absent for a caller that has not been
   * migrated to the retry layer yet, which falls back to the plain "riding"
   * look with no countdown rather than inventing a schedule. */
  failure?: FetchFailure | null;
  /** "Send a rider": try again now, resetting the retry budget. */
  onRetry: () => void;
  /** Abandon the request in flight and stop the schedule behind it. Omitted
   * by callers that have nothing to cancel. */
  onCancel?: () => void;
}

/** Cream disc, four pips, olive needle — the icon pack's compass, redrawn so
 * the needle group can spin. */
function CompassSeeking({ seeking }: { seeking: boolean }) {
  return (
    <svg className="waylaid__compass" viewBox="0 0 64 64" width="36" height="36" aria-hidden="true">
      <circle cx="32" cy="32" r="29" className="waylaid__compass-face" />
      <circle cx="32" cy="32" r="24" className="waylaid__compass-ring" />
      <circle cx="32" cy="9.5" r="1.8" className="waylaid__compass-pip" />
      <circle cx="32" cy="54.5" r="1.8" className="waylaid__compass-pip" />
      <circle cx="9.5" cy="32" r="1.8" className="waylaid__compass-pip" />
      <circle cx="54.5" cy="32" r="1.8" className="waylaid__compass-pip" />
      {/* The needle only turns while a rider is actually out. Spinning under
          "no rider made it through" would promise motion that isn't
          happening — the one thing this strip must never do again. */}
      <g
        className={seeking ? "waylaid__needle" : "waylaid__needle waylaid__needle--still"}
        data-testid="waylaid-needle"
      >
        <polygon points="32,12 37.5,32 26.5,32" className="waylaid__needle-north" />
        <polygon points="32,52 37.5,32 26.5,32" className="waylaid__needle-south" />
        <circle cx="32" cy="32" r="2.6" className="waylaid__compass-pip" />
      </g>
    </svg>
  );
}

export default function Waylaid({ error, failure, onRetry, onCancel }: WaylaidProps) {
  const kind = failure?.kind ?? null;
  const terminal = kind === "auth" || kind === "rejected";
  const waiting = failure?.retryInSeconds ?? null;
  // Riding = a retry is genuinely scheduled. Everything else is at rest.
  const riding = !terminal && waiting !== null;
  // Spent its budget, as opposed to never having had one. The distinction
  // matters: the Chronicle's hook does no automatic retrying at all, and
  // claiming "we sent every rider we had" there would be a second invented
  // schedule on top of the countdown that used to run against nothing.
  const exhausted = failure != null && !terminal && waiting === null;

  // Counts down to the scheduled retry. Keyed off the wait itself so each
  // backoff step restarts it; it does NOT wrap round, because the schedule
  // does not repeat — the next wait is a longer one, set by the hook.
  const [left, setLeft] = useState(waiting ?? 0);
  useEffect(() => {
    if (waiting === null) return;
    setLeft(waiting);
    const id = setInterval(() => setLeft((n) => (n <= 1 ? 0 : n - 1)), 1000);
    return () => clearInterval(id);
  }, [waiting, failure?.retries]);

  const title = terminal
    ? "The gate turned the rider back."
    : exhausted
      ? "No rider made it through."
      : "The messenger has been waylaid.";

  const body = terminal
    ? kind === "auth"
      ? "The keep refused our token. Riding out again will be refused the same way — the token itself has to change."
      : "The keep refused the request itself. Another rider would carry the same refusal."
    : exhausted
      ? "We sent every rider we had and none returned. Nothing further will be tried on its own."
      : riding
        ? "Our courier to the server hasn't come back. Another rider is being saddled."
        : "Our courier to the server hasn't come back.";

  const detail = riding
    ? `${error} · rider ${failure?.retries ?? 1} of ${MAX_RETRIES} leaves in ${left}s`
    : exhausted
      ? `${error} · gave up after ${failure?.retries ?? 0} riders`
      : error;

  return (
    <div className="waylaid" role="alert">
      <CompassSeeking seeking={riding} />
      <div className="waylaid__text">
        <p className="waylaid__title">{title}</p>
        <p className="waylaid__body">{body}</p>
        <p className="waylaid__detail">{detail}</p>
      </div>
      <div className="waylaid__actions">
        <Button className="waylaid__btn" onClick={onRetry}>
          {/* rpg-icons pack "backpack" — decorative (`alt=""`), the accessible
              name stays "Send a rider". */}
          <img src={backpackIcon} alt="" className="waylaid__pack" />
          Send a rider
        </Button>
        {/* Only while something is actually in flight or scheduled — there is
            nothing to call off once the riders are spent or the gate has
            given its final answer. */}
        {onCancel && riding && (
          <Button className="waylaid__btn waylaid__btn--quiet" onClick={onCancel}>
            Call them back
          </Button>
        )}
      </div>
    </div>
  );
}
