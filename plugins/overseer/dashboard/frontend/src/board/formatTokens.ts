/**
 * Compact human display for raw token counts (WF-014). Three bands:
 *  - n < 1,000: verbatim ("950").
 *  - n < 10,000: one decimal, trimmed if it's ".0" ("1500" -> "1.5k", "1000" -> "1k").
 *  - n < 1,000,000: rounded to the nearest k, no decimal ("30000" -> "30k").
 *  - n >= 1,000,000: one decimal, trimmed if it's ".0" ("2000000" -> "2M").
 * Purely cosmetic — callers keep tripwire comparisons on the raw numbers.
 */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n);

  if (n < 1_000_000) {
    if (n < 10_000) return `${trimDecimal((n / 1000).toFixed(1))}k`;
    const k = Math.round(n / 1000);
    // Rounding can carry the k band into the next magnitude (999500 → 1000)
    // — "1000k" is a lie; fall through to the M band instead.
    if (k < 1000) return `${k}k`;
  }

  return `${trimDecimal((n / 1_000_000).toFixed(1))}M`;
}

function trimDecimal(s: string): string {
  return s.endsWith(".0") ? s.slice(0, -2) : s;
}
