/**
 * Deterministic accent-group rotation for party avatars (WF-029 chunk 4) —
 * a presentational hash of a hero's display name/id across the 7 guild
 * column-accent groups. This is NOT data: a hero's actual class is
 * `session.model`, rendered separately by the caller. The same seed always
 * yields the same group, so an avatar's colour stays stable across
 * re-renders/re-polls for as long as the session keeps the same name/id.
 */
export const ACCENT_GROUPS = [
  "forest",
  "amber",
  "sky",
  "orange",
  "rose",
  "umber",
  "taupe",
] as const;

export type AccentGroup = (typeof ACCENT_GROUPS)[number];

export function avatarAccentGroup(seed: string): AccentGroup {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (Math.imul(hash, 31) + seed.charCodeAt(i)) >>> 0;
  }
  return ACCENT_GROUPS[hash % ACCENT_GROUPS.length];
}
