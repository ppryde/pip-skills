import type { PartyMember } from "../board/party";

export interface PartyOverlayProps {
  party: PartyMember[];
  onClose: () => void;
}

/**
 * Party page (HANDOFF §Party page), opened from TopBar's "N questing" pill.
 * Follows CardDetailDrawer's backdrop convention: clicking the backdrop
 * closes, clicking inside the sheet does not (stopPropagation).
 *
 * WF-029 chunk 3 lays down this shell so App.tsx's partyOpen state has a
 * real sibling to render (HANDOFF §State Management). The full hero-card
 * grid — avatar circles, mana bars, ON QUEST lines, the header trio ("The
 * Party" / "N OF M HEROES" / helper line), summon slot — is chunk 6's work.
 */
function PartyOverlay({ party, onClose }: PartyOverlayProps) {
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
        <ul className="party-sheet__list">
          {party.map((member) => (
            <li key={member.session.id}>
              {member.session.session_name || member.session.id}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default PartyOverlay;
