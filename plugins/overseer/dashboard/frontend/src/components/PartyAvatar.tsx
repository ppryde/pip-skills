import type { SessionSummary } from "../api/types";
import { avatarAccentGroup } from "../board/avatarAccent";

export interface PartyAvatarProps {
  session: SessionSummary;
  /** px diameter — 52 for the Party overlay's hero cards (chunk 6), a
   * smaller size for the board column's compact rows (chunk 4). */
  size?: number;
}

/**
 * Deterministic accent-fill circle + initial + a live/stale status dot
 * anchored at the bottom-right corner (HANDOFF §Party page: "avatar circle
 * (accent fill, initial, live green dot bottom-right that pulses)").
 * Shared by PartyColumn (chunk 4) and PartyOverlay (chunk 6) so both
 * surfaces render the exact same avatar for a given session.
 *
 * WF-031: when the session carries a `branch`, it's surfaced here as a
 * hover title ("on <branch>") — the row-level text (PartyColumn/
 * PartyOverlay) is where it's actually READ at a glance; this is just the
 * avatar's own acknowledgement of it, mirroring how `session.stale` shows
 * up as both the dot AND the row's dimmed treatment.
 */
function PartyAvatar({ session, size = 32 }: PartyAvatarProps) {
  const label = session.session_name || session.id;
  const initial = label.charAt(0).toUpperCase();
  const accentGroup = avatarAccentGroup(label);

  return (
    <span
      className={`party-avatar party-avatar--${accentGroup}`}
      style={{ width: size, height: size, fontSize: size * 0.42 }}
      aria-hidden="true"
      title={session.branch ? `on ${session.branch}` : undefined}
    >
      <span className="party-avatar__initial">{initial}</span>
      <span
        className={
          "party-avatar__dot" +
          (session.stale ? " party-avatar__dot--stale" : "")
        }
      />
    </span>
  );
}

export default PartyAvatar;
