/** Defense-in-depth scheme allowlist for anything a card stores as a
 * user-supplied reference — link `path` values (F8/PR5 final-review Fix 1)
 * and the card's `pr` field (WF-073). `Card.from_text`/the CLI already drop
 * or validate non-http(s) values at write time in the common paths, but
 * existing DBs may still hold rows written before those guards existed — so
 * every render site re-checks before ever using such a value as a clickable
 * `href`, closing the `javascript:`/`data:` URI XSS vector on click.
 *
 * Shared by `CardDetailDrawer.tsx` (Links section) and `TileShell.tsx` /
 * `CardDetailDrawer.tsx` (the `pr` chip/link) — one regex, one place to
 * change the scheme allowlist. */
export const HTTP_URL_RE = /^https?:\/\//i;
