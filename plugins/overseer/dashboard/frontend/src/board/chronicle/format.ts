/**
 * Display formatting for the Chronicle page — pure, dependency-free.
 * Token counts reuse `formatTokens` (the board's own compact-number
 * convention) so a "1.2M" here means the same as a "1.2M" on a card.
 */
import { formatTokens } from "../formatTokens";

export { formatTokens };

/** 0 -> "0 B", 1536 -> "1.5 KB", 91148426 -> "86.9 MB". */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${Math.round(n)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

/** Seconds -> "45s", "12m", "3h 05m", "2d 4h". Null/negative -> "—". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h < 24) return `${h}h ${String(rem).padStart(2, "0")}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

/** Milliseconds of active model time -> the same duration words. */
export function formatActive(ms: number): string {
  if (!ms) return "—";
  return formatDuration(ms / 1000);
}

/** Epoch seconds -> "4 Sep 09:41" in the viewer's locale; null -> "—". */
export function formatWhen(epoch: number | null | undefined): string {
  if (epoch === null || epoch === undefined || !Number.isFinite(epoch)) return "—";
  const date = new Date(epoch * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "2026-09-04" -> "4 Sep" (axis label). Falls back to the raw string. */
export function formatDay(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return day;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
}

/**
 * USD -> "$0.42", "$12.30", "$326", "$3.1k"; null -> "—". Sub-cent amounts
 * read "<$0.01" so a tiny session never shows as free.
 */
export function formatUsd(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || !Number.isFinite(usd) || usd < 0) return "—";
  if (usd === 0) return "$0";
  if (usd < 0.01) return "<$0.01";
  if (usd < 100) return `$${usd.toFixed(2)}`;
  if (usd < 1000) return `$${Math.round(usd)}`;
  return `$${(usd / 1000).toFixed(1)}k`;
}

/**
 * A priced-portion cost plus how many turns that price excludes — so a
 * session or day priced entirely on unpriced models reads as "unpriced",
 * never "$0" (a genuinely free session and an unknown-cost one must not
 * look the same). A partially-priced total keeps its number, with a count
 * appended: `formatCostWithUnpriced(0, 3)` -> "unpriced (3)",
 * `formatCostWithUnpriced(1.2, 2)` -> "$1.20 +2 unpriced".
 */
export function formatCostWithUnpriced(usd: number | null | undefined, unpriced: number): string {
  if (unpriced <= 0) return formatUsd(usd);
  if (usd === null || usd === undefined || !Number.isFinite(usd) || usd <= 0) {
    return `unpriced (${unpriced})`;
  }
  return `${formatUsd(usd)} +${unpriced} unpriced`;
}

/** "2026-06-24" -> "Jun 2026" (a tile note has no room for a full date). */
export function formatMonth(day: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(day);
  if (!match) return day;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  return date.toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
}

/** 0.973 -> "97%", null -> "—". */
export function formatPct(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}

/** Where a cache hit rate sits, in a word — so the gauge never means by
 * colour alone. Thresholds are advisory, not a rule the data must obey. */
export function cacheVerdict(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "no data";
  if (ratio >= 0.9) return "warm";
  if (ratio >= 0.7) return "mixed";
  return "cold";
}

/** Model ids are long ("claude-fable-5-1") — strip the vendor prefix for
 * chart labels, keep the id in tooltips/tables. */
export function shortModel(model: string | null): string {
  if (!model) return "unknown";
  return model.replace(/^claude-/, "");
}

/** Session display name: the auto-title when present, else the id's first
 * eight characters (enough to recognise it in a `--resume` list). */
export function sessionName(session: { title: string | null; session_id: string }): string {
  return session.title?.trim() || session.session_id.slice(0, 8);
}

/** Last path segment of a repo root — "/Users/x/repos/pip-skills" -> "pip-skills". */
export function repoLabel(root: string | null): string {
  if (!root) return "—";
  const parts = root.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? root;
}

/**
 * Clean axis ticks: at most `count` round steps (1/2/5 × 10^n) from 0 to a
 * ceiling at or above `max`. `max <= 0` yields a single [0] tick.
 */
export function niceTicks(max: number, count = 4): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0];
  const rough = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const step = (residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 5 ? 5 : 10) * magnitude;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.999; v += step) {
    ticks.push(Number(v.toPrecision(12)));
  }
  return ticks;
}


/** A ratio of two churn figures as a percentage, or "—" when there is nothing
 * to divide by. A tile must never render "NaN%" or invent a 0% that reads as
 * a measured result. */
export function churnRatio(part: number | undefined, whole: number | undefined): string {
  if (!whole) return "—";
  return `${Math.round(((part ?? 0) / whole) * 100)}%`;
}

/** `part / whole` to `dp` places, or "—" when the denominator is missing or
 * zero — same reasoning as `churnRatio`. */
export function perUnit(part: number | undefined, whole: number | undefined, dp: number): string {
  if (!whole) return "—";
  return ((part ?? 0) / whole).toFixed(dp);
}
