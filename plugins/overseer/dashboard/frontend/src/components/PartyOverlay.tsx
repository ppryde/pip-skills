import { useEffect } from "react";
import type { PartyMember } from "../board/party";
import PartyAvatar from "./PartyAvatar";

export interface PartyOverlayProps {
  party: PartyMember[];
  onClose: () => void;
}

/**
 * Party page (HANDOFF §Party page), opened from TopBar's "N questing" pill.
 * Follows CardDetailDrawer's backdrop convention: clicking the backdrop or
 * the close button closes; clicking inside the sheet does not
 * (stopPropagation); Escape closes.
 *
 * Hero-count badge "N OF M HEROES": N = live sessions, M = total known
 * sessions including stale ghosts — both real census data, no invented
 * party capacity (Decisions). LV and the cleared/earned stat tiles are
 * omitted: the app has no level concept and no per-hero cleared/earned
 * metric (spec's honest-data cut) — mana, name, class, and ON QUEST are
 * all real data, so they stay.
 */
function PartyOverlay({ party, onClose }: PartyOverlayProps) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const liveCount = party.filter((m) => !m.session.stale).length;
  const totalCount = party.length;

  return (
    <div className="party-overlay" data-testid="party-overlay" onClick={onClose}>
      <div
        className="party-sheet"
        role="dialog"
        aria-label="The Party"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="party-sheet__close"
          onClick={onClose}
          aria-label="Close"
        >
          ×
        </button>

        <div className="party-sheet__header">
          <h2 className="party-sheet__title">⚔ The Party</h2>
          <span className="party-sheet__count">
            {liveCount} OF {totalCount} HEROES
          </span>
        </div>
        <p className="party-sheet__helper">
          …their mana is the context they have left.
        </p>

        <div className="party-sheet__grid">
          {party.map((member) => {
            const { session } = member;
            const mana = session.pct === undefined ? null : 100 - session.pct;
            return (
              <div key={session.id} className="hero-card">
                <PartyAvatar session={session} size={52} />
                <div className="hero-card__name">
                  {session.session_name || session.id}
                </div>
                {session.model && (
                  <div className="hero-card__class">{session.model}</div>
                )}
                {mana === null ? (
                  <div className="hero-card__mana hero-card__mana--unknown">
                    <span className="hero-card__mana-label">— unknown</span>
                  </div>
                ) : (
                  <div className="hero-card__mana">
                    <div
                      className={
                        "hero-card__mana-fill hero-card__mana-fill--" +
                        (mana >= 50 ? "high" : "low")
                      }
                      style={{ width: `${mana}%` }}
                    />
                  </div>
                )}
                {member.questCardId && (
                  <div className="hero-card__quest">
                    <div className="hero-card__quest-label">
                      ON QUEST · {member.questCardId}
                    </div>
                    <div className="hero-card__quest-title">
                      {member.questTitle}
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          {/* Static, non-interactive — open session slots, not a party-size
              limit the app invents (Decisions). */}
          <div className="hero-card hero-card--summon">Summon a hero</div>
        </div>
      </div>
    </div>
  );
}

export default PartyOverlay;
