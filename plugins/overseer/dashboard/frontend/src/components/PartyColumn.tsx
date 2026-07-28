import type { PartyMember } from "../board/party";
import { prLabel } from "../board/prLabel";
import PartyAvatar from "./PartyAvatar";

export interface PartyColumnProps {
  party: PartyMember[];
  /** WF-031 branch filter: `null`/absent clears it; otherwise every row
   * whose session `branch` matches gets the `is-spotlight` treatment.
   * Unlike cards, non-matching rows are NOT dimmed — the Party stays fully
   * legible, only the active branch's own heroes get called out. */
  activeBranch?: string | null;
  /** WF-042: the fleet's global default (`context.threshold`) — a row gets
   * the `is-near-threshold` cue when its own session's `pct >= threshold`.
   * `null`/absent means no threshold is set, so the cue never fires. */
  threshold?: number | null;
}

/**
 * Dark "Party" panel at the board scroll-row's tail (HANDOFF §Board:
 * "Rightmost item in the scroll row is the Party panel"). Renders one row
 * per census session, live or stale — stale sessions stay visible as
 * dimmed ghost rows rather than disappearing, so a hero who just went
 * quiet isn't erased from view mid-glance.
 *
 * Each row surfaces a single "Exhaustion" bar (`session.pct`, fills UP as
 * context is used — 0% fresh, 100% spent — replacing the old inverse
 * `mana` bar and the separate WF-042 ctx% line, which were two
 * representations of the same number pulling in opposite directions).
 * `pct === undefined` (SessionSummary.pct is optional, census-derived) is
 * guarded explicitly: the bar is simply omitted rather than rendered with
 * a NaN width.
 *
 * Each row also surfaces the session's PR (`session.pr`, linked when
 * `pr.url` is present) and gets the `is-near-threshold` cue when that pct
 * is at/over the fleet's global default threshold — same fields/cue as
 * PartyOverlay's hero cards, just in the compact row layout.
 */
function PartyColumn({
  party,
  activeBranch = null,
  threshold = null,
}: PartyColumnProps) {
  return (
    <div className="party-column">
      <div className="party-column__header">Party</div>
      <div className="party-column__rows">
        {party.map((member) => {
          const { session } = member;
          const spotlight =
            activeBranch !== null && session.branch === activeBranch;
          const isNearThreshold =
            session.pct !== undefined &&
            threshold !== null &&
            session.pct >= threshold;
          return (
            <div
              key={session.id}
              className={
                "party-row" +
                (session.stale ? " party-row--stale" : "") +
                (spotlight ? " is-spotlight" : "") +
                (isNearThreshold ? " is-near-threshold" : "")
              }
            >
              <PartyAvatar session={session} size={32} />
              <div className="party-row__body">
                <div className="party-row__name">
                  {session.session_name || session.id}
                </div>
                {session.model && (
                  <div className="party-row__class">{session.model}</div>
                )}
                {session.branch && (
                  <div className="party-row__branch">⑃ {session.branch}</div>
                )}
                {session.pct !== undefined && (
                  <div className="party-row__exhaustion">
                    <div className="party-row__exhaustion-row">
                      <span className="party-row__exhaustion-label">
                        Exhaustion
                      </span>
                      <span className="party-row__exhaustion-value">
                        {session.pct}%
                      </span>
                    </div>
                    <div className="party-row__exhaustion-bar">
                      <div
                        className={
                          "party-row__exhaustion-fill party-row__exhaustion-fill--" +
                          (session.pct >= 50 ? "high" : "low")
                        }
                        style={{ width: `${session.pct}%` }}
                      />
                    </div>
                  </div>
                )}
                {session.pr && (
                  <div className="party-row__pr">
                    {session.pr.url ? (
                      <a
                        className="party-row__pr-link"
                        href={session.pr.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {prLabel(session.pr)}
                      </a>
                    ) : (
                      prLabel(session.pr)
                    )}
                  </div>
                )}
                {member.questCardId && (
                  <div className="party-row__quest">
                    ON QUEST · {member.questCardId} — {member.questTitle}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PartyColumn;
