/**
 * Curated palette keys — stable label -> swatch mapping (F1, WF-058). Maps
 * each label string to ONE of these keys via a simple deterministic string
 * hash, so the SAME label renders the SAME chip colour everywhere on the
 * board (tile + drawer) and across re-renders — never random, never
 * re-picked per mount. CSS (`.label-chip--<key>` in styles.css) owns the
 * actual bg/text/border values; this module only owns the label -> key
 * assignment.
 *
 * This is NOT the F10 editable colour registry (WF-067, deferred) — there is
 * no per-project configuration and no user-chosen colours here, just enough
 * spread across a curated, readable palette that two distinct labels usually
 * (not guaranteed — it's a fixed-size hash bucket) land on different
 * swatches.
 */
const PALETTE_KEYS = [
  "slate",
  "sage",
  "plum",
  "clay",
  "sky",
  "violet",
  "olive",
  "terracotta",
  "teal",
] as const;

export type LabelSwatchKey = (typeof PALETTE_KEYS)[number];

/** djb2 string hash — cheap, deterministic, no external dependency. Bitwise
 * OR with 0 keeps the running hash in 32-bit signed int range (same trick
 * used for fast string hashing generally); `Math.abs` folds the sign back
 * out so the modulo below is never negative. */
function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = (h * 33 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/**
 * Deterministically maps `label` to a swatch key. When `registry` (the F10
 * editable colour registry, WF-067 — board payload's `label_colors`) has an
 * entry for `label`, that user-chosen key wins; otherwise falls back to the
 * curated-palette hash above, byte-identical to the no-registry behaviour
 * this function always had.
 */
export function labelColor(
  label: string,
  registry?: Record<string, string>
): string {
  return registry?.[label] ?? PALETTE_KEYS[hashString(label) % PALETTE_KEYS.length];
}
