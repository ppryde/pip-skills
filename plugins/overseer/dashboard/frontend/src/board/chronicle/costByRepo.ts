/**
 * Cost per day, stacked by repo. Chronicle's server-side `by_day` (from
 * `summary()`) sums turns across every repo in scope and has no per-repo
 * column, so a repo breakdown is built client-side from `sessions` — which
 * every "all repos" fetch already carries for the sessions table below.
 */
import type { ChronicleSession } from "../../api/types";
import { formatDay, repoLabel } from "./format";

export interface RepoCostSeries {
  /** Grouping key: the raw `repo_root`, the no-repo sentinel, or the
   * "Other" sentinel. Stable regardless of rank, so a repo's identity never
   * changes as the window or branch filter changes which repos are in it. */
  key: string;
  label: string;
  total: number;
}

export interface RepoCostPoint {
  label: string;
  /** Full day string ("2026-09-21"), for the tooltip/table. */
  detail: string;
  /** One entry per `series`, in the same order, zero-filled when that repo
   * had no session on this day — every point has every series, so stacks
   * stay aligned bar to bar. */
  segments: { key: string; value: number }[];
}

export interface CostByRepo {
  series: RepoCostSeries[];
  points: RepoCostPoint[];
}

const NO_REPO = "__no_repo__";
const OTHER = "__other__";

/** Local calendar day ("2026-09-21") a session started on. */
function dayKey(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Repos beyond `maxSeries` fold into one "Other repos" series, ranked by
 * total cost across the whole window. Which repos are individually named
 * can change with the window — but that only ever changes "Other"'s
 * membership, never an already-named repo's key, so a chart assigning
 * colour by key stays stable across filter changes.
 */
export function costByRepo(sessions: ChronicleSession[], maxSeries = 7): CostByRepo {
  const totalByRepo = new Map<string, number>();
  const labelByRepo = new Map<string, string>();
  const byDay = new Map<string, Map<string, number>>();

  for (const s of sessions) {
    if (s.started_at === null || !Number.isFinite(s.started_at)) continue;
    const key = s.repo_root ?? NO_REPO;
    const cost = s.cost_usd ?? 0;
    totalByRepo.set(key, (totalByRepo.get(key) ?? 0) + cost);
    labelByRepo.set(key, s.repo_root ? repoLabel(s.repo_root) : "No repo");
    const day = dayKey(s.started_at);
    const perRepo = byDay.get(day) ?? new Map<string, number>();
    perRepo.set(key, (perRepo.get(key) ?? 0) + cost);
    byDay.set(day, perRepo);
  }

  const ranked = [...totalByRepo.entries()].sort((a, b) => b[1] - a[1]);
  const shownKeys = new Set(ranked.slice(0, maxSeries).map(([key]) => key));
  const foldedKeys = ranked.filter(([key]) => !shownKeys.has(key)).map(([key]) => key);

  const series: RepoCostSeries[] = ranked
    .filter(([key]) => shownKeys.has(key))
    .map(([key, total]) => ({ key, label: labelByRepo.get(key) ?? key, total }));
  if (foldedKeys.length > 0) {
    const total = foldedKeys.reduce((sum, key) => sum + (totalByRepo.get(key) ?? 0), 0);
    series.push({ key: OTHER, label: "Other repos", total });
  }

  const points: RepoCostPoint[] = [...byDay.keys()].sort().map((day) => {
    const perRepo = byDay.get(day)!;
    const segments = series.map(({ key }) =>
      key === OTHER
        ? { key, value: foldedKeys.reduce((sum, k) => sum + (perRepo.get(k) ?? 0), 0) }
        : { key, value: perRepo.get(key) ?? 0 }
    );
    return { label: formatDay(day), detail: day, segments };
  });

  return { series, points };
}
