/**
 * The Chronicle — session telemetry from the optional chronicle plugin.
 *
 * Pull on demand: the page never ingests anything by itself. "Sync" asks the
 * backend to reconcile chronicle's store with the transcripts on disk, then
 * re-reads. Everything below the toolbar is scoped by the same filter row:
 * a time window and a repo scope (this repo = the dashboard's active root,
 * the same choke point the board uses; all = account-wide).
 */
import { useCallback, useMemo, useState } from "react";
import { syncChronicle } from "../../api/client";
import type { ChronicleSession, ChronicleSyncResponse } from "../../api/types";
import { useChronicle } from "../../board/chronicle/useChronicle";
import {
  cacheVerdict,
  formatActive,
  formatBytes,
  formatDay,
  formatDuration,
  formatPct,
  formatTokens,
  formatWhen,
  repoLabel,
  sessionName,
  shortModel,
} from "../../board/chronicle/format";
import { Button } from "../../ui";
import { BarList, ColumnChart } from "./ChronicleCharts";
import Gauge from "./Gauge";
import SessionDrawer from "./SessionDrawer";
import StatTile from "./StatTile";

export interface ChroniclePageProps {
  /** The dashboard's active repo root (null = launch root). */
  activeRoot: string | null;
  /** False for an "unbegun" repo, whose root the backend refuses on every
   * scoped read — the page then locks the scope to "All repos". */
  repoScopable: boolean;
}

const WINDOWS: { label: string; days: number | undefined }[] = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "All time", days: undefined },
];

type SortKey =
  | "started_at"
  | "turns"
  | "prompts"
  | "tool_calls"
  | "peak_context_tokens"
  | "output_tokens"
  | "duration_s"
  | "transcript_bytes";

const COLUMNS: { key: SortKey; label: string; render: (s: ChronicleSession) => string }[] = [
  { key: "started_at", label: "Started", render: (s) => formatWhen(s.started_at) },
  { key: "duration_s", label: "Span", render: (s) => formatDuration(s.duration_s) },
  { key: "turns", label: "Turns", render: (s) => String(s.turns) },
  { key: "prompts", label: "Prompts", render: (s) => String(s.prompts) },
  { key: "tool_calls", label: "Tools", render: (s) => String(s.tool_calls) },
  { key: "peak_context_tokens", label: "Peak ctx", render: (s) => formatTokens(s.peak_context_tokens) },
  { key: "peak_context_tokens", label: "Peak %", render: (s) => formatPct(s.peak_context_pct) },
  { key: "output_tokens", label: "Output", render: (s) => formatTokens(s.output_tokens) },
  { key: "transcript_bytes", label: "Size", render: (s) => formatBytes(s.transcript_bytes) },
];

function sortSessions(rows: ChronicleSession[], key: SortKey, dir: "asc" | "desc"): ChronicleSession[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[key] ?? -Infinity;
    const bv = b[key] ?? -Infinity;
    return av === bv ? 0 : av > bv ? sign : -sign;
  });
}

function syncSummary(res: ChronicleSyncResponse): string {
  if (res.changed === 0) return `Synced — nothing new across ${res.scanned} files.`;
  const noun = res.changed === 1 ? "session" : "sessions";
  return `Synced — ${res.changed} ${noun} updated (${res.lines} new lines).`;
}

export default function ChroniclePage({ activeRoot, repoScopable }: ChroniclePageProps) {
  const [days, setDays] = useState<number | undefined>(30);
  const [scopeAll, setScopeAll] = useState(false);
  const scope: "repo" | "all" = scopeAll || !repoScopable ? "all" : "repo";
  const { summary, sessions, loading, error, refresh } = useChronicle(
    activeRoot,
    { days, scope },
    true
  );
  const [openId, setOpenId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("started_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  const sync = useCallback(async () => {
    setSyncing(true);
    setSyncNote(null);
    try {
      const res = await syncChronicle();
      setSyncNote(syncSummary(res));
      await refresh();
    } catch (err) {
      setSyncNote(`Sync failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSyncing(false);
    }
  }, [refresh]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const ordered = useMemo(() => sortSessions(sessions, sortKey, sortDir), [sessions, sortKey, sortDir]);
  const totals = summary?.totals ?? null;
  const byDay = summary?.by_day ?? [];
  const contextPerDay = byDay.map((d) => ({
    label: formatDay(d.day),
    detail: d.day,
    value: d.input_tokens + d.cache_read_tokens + d.cache_creation_tokens,
  }));
  const outputPerDay = byDay.map((d) => ({ label: formatDay(d.day), detail: d.day, value: d.output_tokens }));
  const peakPerDay = byDay.map((d) => ({
    label: formatDay(d.day),
    detail: `${d.day} · ${formatPct(d.peak_context_pct)} of window`,
    value: d.peak_context_tokens,
  }));
  const hitRatePerDay = byDay.map((d) => ({
    label: formatDay(d.day),
    detail: `${d.day} · ${d.cold_turns} cold`,
    value: d.cache_hit_rate ?? 0,
  }));
  const shape = summary?.shape;
  const closeDrawer = useCallback(() => setOpenId(null), []);

  return (
    <div className={`chronicle${loading && summary ? " chronicle--refreshing" : ""}`}>
      <div className="chronicle__toolbar" role="group" aria-label="Chronicle filters">
        <div className="chronicle__segment" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <Button
              key={w.label}
              aria-pressed={days === w.days}
              onClick={() => setDays(w.days)}
              className="chronicle__seg-btn"
            >
              {w.label}
            </Button>
          ))}
        </div>
        <div className="chronicle__segment" role="group" aria-label="Repo scope">
          <Button
            aria-pressed={scope === "repo"}
            disabled={!repoScopable}
            title={repoScopable ? undefined : "This repo has no board yet; showing every repo"}
            onClick={() => setScopeAll(false)}
            className="chronicle__seg-btn"
          >
            This repo
          </Button>
          <Button
            aria-pressed={scope === "all"}
            onClick={() => setScopeAll(true)}
            className="chronicle__seg-btn"
          >
            All repos
          </Button>
        </div>
        <div className="chronicle__sync">
          {syncNote && <span className="chronicle__sync-note" role="status">{syncNote}</span>}
          <Button variant="primary" onClick={() => void sync()} disabled={syncing}>
            {syncing ? "Syncing…" : "Sync"}
          </Button>
        </div>
      </div>

      {error && <p className="board-error">{error}</p>}

      {summary && totals === null && (
        <div className="chronicle__empty">
          <p className="chronicle__empty-title">The chronicle is blank.</p>
          <p>Press <strong>Sync</strong> to read every session transcript on this machine into it.</p>
        </div>
      )}

      {totals && (
        <>
          <div className="chr-hero">
            <Gauge
              value={totals.cache_hit_rate}
              display={formatPct(totals.cache_hit_rate)}
              label="Cache hit rate"
              verdict={cacheVerdict(totals.cache_hit_rate)}
              note={`${formatTokens(totals.cache_creation_tokens)} written · ${formatTokens(totals.cold_turns)} cold turns`}
              hue="--chr-cache"
            />
            <Gauge
              value={totals.peak_context_pct}
              display={formatPct(totals.peak_context_pct)}
              label="Peak context used"
              verdict={`${formatTokens(totals.peak_context_tokens)} of ${formatTokens(totals.context_window)}`}
              note="largest single window any session reached"
              hue="--chr-peak"
            />
          </div>

          <div className="chr-tiles">
            <StatTile
              label="Sessions"
              value={String(totals.sessions)}
              note={totals.live > 0 ? `${totals.live} live` : undefined}
            />
            <StatTile
              label="Turns"
              value={formatTokens(totals.turns)}
              note={`${formatTokens(totals.prompts)} prompts`}
              hue="--chr-turns"
            />
            <StatTile label="Tool calls" value={formatTokens(totals.tool_calls)} hue="--chr-tools" />
            <StatTile
              label="Context processed"
              value={formatTokens(totals.input_tokens + totals.cache_read_tokens + totals.cache_creation_tokens)}
              note={`${formatTokens(totals.cache_read_tokens)} from cache`}
            />
            <StatTile
              label="Output tokens"
              value={formatTokens(totals.output_tokens)}
              note={`${formatTokens(totals.thinking_tokens)} thinking`}
              hue="--chr-output"
            />
            <StatTile label="Active time" value={formatActive(totals.active_ms)} hue="--chr-turns" />
            <StatTile
              label="Transcripts"
              value={formatBytes(totals.transcript_bytes)}
              hue="--chr-tools"
            />
            <StatTile
              label="Subagents"
              value={String(totals.subagents)}
              note={`${totals.compactions} compactions`}
              hue="--chr-peak"
            />
            <StatTile
              label="Cache written"
              value={formatTokens(totals.cache_creation_tokens)}
              note={`${formatTokens(totals.cache_1h_tokens)} at 1h · ${formatTokens(totals.cache_5m_tokens)} at 5m`}
              hue="--chr-cache"
            />
          </div>

          <div className="chronicle__grid">
            <section className="chr-panel">
              <h3 className="chr-panel__title">Context processed per day</h3>
              <p className="chr-panel__sub">Input + cache read + cache creation, every API call.</p>
              <ColumnChart points={contextPerDay} format={formatTokens} title="Context tokens per day" hue="--chr-context" />
            </section>
            <section className="chr-panel">
              <h3 className="chr-panel__title">Output per day</h3>
              <p className="chr-panel__sub">Tokens the model wrote, thinking included.</p>
              <ColumnChart points={outputPerDay} format={formatTokens} title="Output tokens per day" hue="--chr-output" />
            </section>
            <section className="chr-panel">
              <h3 className="chr-panel__title">Peak context per day</h3>
              <p className="chr-panel__sub">Largest single window any session reached that day.</p>
              <ColumnChart points={peakPerDay} format={formatTokens} title="Peak context tokens per day" hue="--chr-peak" />
            </section>
            <section className="chr-panel">
              <h3 className="chr-panel__title">Cache hit rate per day</h3>
              <p className="chr-panel__sub">Share of context read back from cache; hover for cold turns.</p>
              <ColumnChart points={hitRatePerDay} format={formatPct} title="Cache hit rate per day" hue="--chr-cache" />
            </section>
            <section className="chr-panel">
              <h3 className="chr-panel__title">Turns by model</h3>
              <BarList
                rows={(summary?.by_model ?? []).map((m) => ({
                  label: shortModel(m.model),
                  detail: `${m.model} · ${m.sessions} sessions · ${formatTokens(m.output_tokens)} output`,
                  value: m.turns,
                }))}
                format={formatTokens}
                title="Turns by model"
                hue="--chr-turns"
              />
            </section>
            <section className="chr-panel">
              <h3 className="chr-panel__title">Tool calls</h3>
              <BarList
                rows={(summary?.tools ?? []).slice(0, 10).map((t) => ({
                  label: t.tool_name,
                  detail: `${t.calls} calls across ${t.sessions ?? "?"} sessions`,
                  value: t.calls,
                }))}
                format={formatTokens}
                title="Tool calls"
                hue="--chr-tools"
              />
            </section>
            {shape && (
              <section className="chr-panel chr-panel--wide">
                <h3 className="chr-panel__title">Session shape</h3>
                <p className="chr-panel__sub">What a typical session looks like in this window.</p>
                <table className="chr-table chr-table--compact">
                  <thead>
                    <tr>
                      <th scope="col">Measure</th>
                      <th scope="col" className="chr-num">Median</th>
                      <th scope="col" className="chr-num">p90</th>
                      <th scope="col" className="chr-num">Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ["Turns", shape.turns, (n: number) => String(Math.round(n))],
                        ["Prompts", shape.prompts, (n: number) => String(Math.round(n))],
                        ["Span", shape.duration_s, formatDuration],
                        ["Peak context", shape.peak_context_tokens, formatTokens],
                        ["Transcript size", shape.transcript_bytes, formatBytes],
                      ] as const
                    ).map(([label, q, fmt]) => (
                      <tr key={label}>
                        <th scope="row">{label}</th>
                        <td className="chr-num">{q.p50 === null ? "—" : fmt(q.p50)}</td>
                        <td className="chr-num">{q.p90 === null ? "—" : fmt(q.p90)}</td>
                        <td className="chr-num">{q.max === null ? "—" : fmt(q.max)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </div>

          <section className="chr-panel chr-panel--wide">
            <h3 className="chr-panel__title">Sessions</h3>
            {ordered.length === 0 ? (
              <p className="chr-chart__empty">No sessions in this window.</p>
            ) : (
              <div className="chr-table-wrap">
                <table className="chr-table" aria-label="Sessions">
                  <thead>
                    <tr>
                      <th scope="col">Session</th>
                      <th scope="col">Repo · branch</th>
                      {COLUMNS.map((c) => (
                        <th
                          key={c.key}
                          scope="col"
                          className="chr-num"
                          aria-sort={sortKey === c.key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                        >
                          <button type="button" className="chr-table__sort" onClick={() => onSort(c.key)}>
                            {c.label}
                            {sortKey === c.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ordered.map((s) => (
                      <tr key={s.session_id} className="chr-table__row" onClick={() => setOpenId(s.session_id)}>
                        <td>
                          <button type="button" className="chr-table__open" onClick={(e) => { e.stopPropagation(); setOpenId(s.session_id); }}>
                            {sessionName(s)}
                          </button>
                          <span className="chr-table__sub chr-mono">{s.session_id.slice(0, 8)}</span>
                          {s.live && <span className="chr-live">live</span>}
                        </td>
                        <td>
                          <span>{repoLabel(s.repo_root)}</span>
                          {s.git_branch && <span className="chr-table__sub chr-mono">{s.git_branch}</span>}
                        </td>
                        {COLUMNS.map((c) => (
                          <td key={c.key} className="chr-num">
                            {c.render(s)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      {summary === null && !error && <p className="board-placeholder">Loading chronicle…</p>}

      <SessionDrawer sessionId={openId} onClose={closeDrawer} />
    </div>
  );
}
