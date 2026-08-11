/**
 * Deterministic epic "beast" generator (Epic Atlas, WF-086). The beast
 * doodle waiting at a campaign trail's end is derived entirely from the
 * epic card's id — no storage, stable across renders/reloads, and the same
 * beast on every machine that renders the same epic. Same djb2 hash pattern
 * as `labelColor.ts`'s `hashString`, kept local here rather than shared so
 * this module has no import surface a future per-epic override field would
 * need to route around (see HANDOFF's "keep the generator in its own tested
 * module" note).
 */

const EPITHETS = [
  "Tiny-Screen",
  "Unmapped",
  "Lingering",
  "Threadbare",
  "Half-Charted",
  "Moth-Eaten",
  "Backlogged",
  "Undocumented",
  "Off-By-One",
  "Deprecated",
] as const;

const NOUNS = [
  "Terror",
  "Vast",
  "Shade",
  "Horde",
  "Wraith",
  "Sprawl",
  "Gloom",
  "Reckoning",
  "Tangle",
  "Husk",
] as const;

/** djb2 string hash — see `labelColor.ts` for the identical pattern and
 * rationale (32-bit wrap via `| 0`, `Math.abs` to keep modulo non-negative). */
function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = (h * 33 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

export interface Beast {
  name: string;
  horns: boolean;
  hueVariant: 0 | 1;
}

/**
 * Hashes `cardId` (salted per attribute so epithet/noun/horns/hue don't all
 * move together off a single hash value) into a curated word-list pair plus
 * two cosmetic flags. Pure and deterministic: same id in, same beast out,
 * every time, on every machine.
 */
export function beastFor(cardId: string): Beast {
  const epithet = EPITHETS[hashString(cardId) % EPITHETS.length];
  const noun = NOUNS[hashString(cardId + "::noun") % NOUNS.length];
  const horns = hashString(cardId + "::horns") % 2 === 0;
  const hueVariant = (hashString(cardId + "::hue") % 2) as 0 | 1;

  return { name: `The ${epithet} ${noun}`, horns, hueVariant };
}
