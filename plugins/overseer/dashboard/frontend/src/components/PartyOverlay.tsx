import { useEffect } from "react";
import type { PartyMember } from "../board/party";
import { prLabel } from "../board/prLabel";
import PartyAvatar from "./PartyAvatar";

/** WF-084: short display form of a census session id — first 8 chars plus
 * an ellipsis when the id runs longer, verbatim otherwise. The full id
 * always stays available via the card's `title` attribute. */
function shortSessionId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export interface PartyOverlayProps {
  party: PartyMember[];
  onClose: () => void;
  /** WF-031 branch filter: `null`/absent clears it; otherwise every hero
   * card whose session `branch` matches gets the `is-spotlight` treatment
   * (see PartyColumn's doc comment — no dimming of non-matching heroes
   * here). */
  activeBranch?: string | null;
  /** WF-042: the fleet's global default (`context.threshold`, threaded down
   * from App.tsx) — a hero card gets the `is-near-threshold` warning cue
   * when its own `session.pct >= threshold`. `null`/absent means no
   * threshold is set, so the cue never fires. */
  threshold?: number | null;
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
 * metric (spec's honest-data cut) — exhaustion, name, class, and ON QUEST
 * are all real data, so they stay.
 *
 * Each hero card also surfaces a single "Exhaustion" bar (`session.pct`,
 * fills UP as context is used — 0% fresh, 100% spent — replacing the old
 * inverse `mana` bar and the separate WF-042 ctx% line, which were two
 * representations of the same number pulling in opposite directions), its
 * PR (`session.pr`, linked when `pr.url` is present), and an `is-near-
 * threshold` cue when that pct is at/over the fleet's global default
 * threshold. All mirror the "forward what's there" style already used for
 * model/branch below — absent fields simply render nothing.
 */
function PartyOverlay({
  party,
  onClose,
  activeBranch = null,
  threshold = null,
}: PartyOverlayProps) {
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
          …their exhaustion is the context they've spent.
        </p>

        <div className="party-sheet__grid">
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
                  "hero-card" +
                  (spotlight ? " is-spotlight" : "") +
                  (isNearThreshold ? " is-near-threshold" : "")
                }
              >
                <PartyAvatar session={session} size={52} />
                <div className="hero-card__name">
                  {session.session_name || session.id}
                </div>
                <div
                  className="hero-card__session-id"
                  title={session.id}
                  style={{ fontSize: "0.7em", opacity: 0.6 }}
                >
                  {shortSessionId(session.id)}
                </div>
                {session.model && (
                  <div className="hero-card__class">{session.model}</div>
                )}
                {session.branch && (
                  <div className="hero-card__branch">⑃ {session.branch}</div>
                )}
                {session.pct !== undefined && (
                  <div className="hero-card__exhaustion">
                    <div className="hero-card__exhaustion-row">
                      <span className="hero-card__exhaustion-label">
                        Exhaustion
                      </span>
                      <span className="hero-card__exhaustion-value">
                        {session.pct}%
                      </span>
                    </div>
                    <div className="hero-card__exhaustion-bar">
                      <div
                        className={
                          "hero-card__exhaustion-fill hero-card__exhaustion-fill--" +
                          (session.pct >= 50 ? "high" : "low")
                        }
                        style={{ width: `${session.pct}%` }}
                      />
                    </div>
                  </div>
                )}
                {session.pr && (
                  <div className="hero-card__pr">
                    {session.pr.url ? (
                      <a
                        className="hero-card__pr-link"
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
