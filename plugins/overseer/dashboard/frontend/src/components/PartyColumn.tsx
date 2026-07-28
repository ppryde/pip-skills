import type { PartyMember } from "../board/party";
import PartyAvatar from "./PartyAvatar";

export interface PartyColumnProps {
  party: PartyMember[];
  /** WF-031 branch filter: `null`/absent clears it; otherwise every row
   * whose session `branch` matches gets the `is-spotlight` treatment.
   * Unlike cards, non-matching rows are NOT dimmed — the Party stays fully
   * legible, only the active branch's own heroes get called out. */
  activeBranch?: string | null;
}

/**
 * Dark "Party" panel at the board scroll-row's tail (HANDOFF §Board:
 * "Rightmost item in the scroll row is the Party panel"). Renders one row
 * per census session, live or stale — stale sessions stay visible as
 * dimmed ghost rows rather than disappearing, so a hero who just went
 * quiet isn't erased from view mid-glance.
 *
 * Mana bar guards `pct === undefined` explicitly: SessionSummary.pct is
 * optional (census-derived, may be absent), and `100 - undefined` is NaN,
 * not a sensible width. The undefined case renders the same neutral
 * "— unknown" treatment the topbar's own ctx display already used.
 */
function PartyColumn({ party, activeBranch = null }: PartyColumnProps) {
  return (
    <div className="party-column">
      <div className="party-column__header">Party</div>
      <div className="party-column__rows">
        {party.map((member) => {
          const { session } = member;
          const mana = session.pct === undefined ? null : 100 - session.pct;
          const spotlight =
            activeBranch !== null && session.branch === activeBranch;
          return (
            <div
              key={session.id}
              className={
                "party-row" +
                (session.stale ? " party-row--stale" : "") +
                (spotlight ? " is-spotlight" : "")
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
                {mana === null ? (
                  <div className="party-row__mana party-row__mana--unknown">
                    <span className="party-row__mana-label">— unknown</span>
                  </div>
                ) : (
                  <div className="party-row__mana">
                    <div
                      className={
                        "party-row__mana-fill party-row__mana-fill--" +
                        (mana >= 50 ? "high" : "low")
                      }
                      style={{ width: `${mana}%` }}
                    />
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
