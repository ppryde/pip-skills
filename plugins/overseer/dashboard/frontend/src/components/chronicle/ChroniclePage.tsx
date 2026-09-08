/**
 * The Chronicle — session telemetry from the optional chronicle plugin.
 *
 * Pull on demand: the page never ingests anything by itself. Its controls
 * live in the top bar (App.tsx): "Sync" where the board's ＋ sits, and the
 * time-window / repo-scope filters in the shared "Filters ▾" region
 * (`<ChronicleFilterBar/>`). App owns that state and the `useChronicle`
 * fetch, and hands this page the result — so this file is the reading of
 * the data, not the fetching of it.
 */
import { useCallback, useMemo, useState } from "react";
import type { ChronicleSession } from "../../api/types";
import type { UseChronicleResult } from "../../board/chronicle/useChronicle";
import {
  cacheVerdict,
  formatActive,
  formatBytes,
  formatCostWithUnpriced,
  churnRatio,
  formatDay,
  formatDuration,
  formatMonth,
  formatPct,
  formatTokens,
  formatUsd,
  perUnit,
  formatWhen,
  repoLabel,
  sessionName,
  shortModel,
} from "../../board/chronicle/format";
import { windowInsights } from "../../board/chronicle/insights";
import { Button } from "../../ui";
import { planLabel, plansPresent } from "../../board/chronicle/plan";
import Waylaid from "../Waylaid";
import ArtifactList from "./ArtifactList";
import CounselPanel from "./CounselPanel";
import { BarList, ColumnChart, Donut } from "./ChronicleCharts";
import Gauge from "./Gauge";
import SessionDrawer from "./SessionDrawer";
import CostAttributionPanel from "./CostAttributionPanel";
import DelegationPanel from "./DelegationPanel";
import StatTile from "./StatTile";
import McpExplorer from "./McpExplorer";
import UsageCallout from "./UsageCallout";

/** The `useChronicle` result, as App.tsx fetched it for the current window
 * and scope, plus a retry for the fetch-failure banner. Sync lives in the
 * top bar, so `refresh` itself is not needed here. */
export type ChroniclePageProps = Omit<UseChronicleResult, "refresh"> & {
  /** "Send a rider": re-fetch now after a failure. */
  onRetry: () => void;
  /** The active scope. The plan filter only appears under "all": within one
   * repo the sessions are nearly always a single plan, so the control would
   * be a permanent no-op taking up room. */
  scope?: "repo" | "all";
};

/** useChronicle's poll cadence, for the fetch-failure banner's countdown. */
const CHRONICLE_RETRY_SECONDS = 30;

/** Columns that sort on a field of the row, by that field's name. */
type RowSortKey =
  | "started_at"
  | "artifacts"
  | "turns"
  | "prompts"
  | "tool_calls"
  | "subagents"
  | "peak_context_tokens"
  | "peak_context_pct"
  | "output_tokens"
  | "duration_s"
  | "transcript_bytes"
  | "files_touched"
  | "cost_usd";

/** Columns that sort on something the row does not carry as a field. Every
 * one of these MUST appear in `SORT_VALUE` — the type says so, so adding a
 * derived column without its comparator is a compile error rather than a
 * column that silently refuses to sort. */
type DerivedSortKey = "lines";

type SortKey = RowSortKey | DerivedSortKey;

/** "Lines" shows `+a / -r` and ranks on the two summed: a big deletion is as
 * much editing as a big addition. */
const SORT_VALUE: Record<DerivedSortKey, (s: ChronicleSession) => number> = {
  lines: (s) => s.lines_added + s.lines_removed,
};

/** Churn is zero both when a session edited nothing and when its transcript
 * was pruned before ingest, and the store cannot tell those apart — so zero
 * reads as "—", the same treatment Artifacts and Subagents already give it,
 * rather than as a claim that no editing happened. */
function churnCell(s: ChronicleSession): string {
  if (s.lines_added === 0 && s.lines_removed === 0) return "—";
  return `+${formatTokens(s.lines_added)} / -${formatTokens(s.lines_removed)}`;
}

const COLUMNS: { key: SortKey; label: string; render: (s: ChronicleSession) => string }[] = [
  { key: "started_at", label: "Started", render: (s) => formatWhen(s.started_at) },
  { key: "duration_s", label: "Span", render: (s) => formatDuration(s.duration_s) },
  { key: "turns", label: "Turns", render: (s) => String(s.turns) },
  { key: "prompts", label: "Prompts", render: (s) => String(s.prompts) },
  { key: "tool_calls", label: "Tools", render: (s) => String(s.tool_calls) },
  // Beside Tools: both count what the session DID. An em dash rather than a
  // bare 0 so a session that never delegated reads as "none", matching the
  // Artifacts column's treatment of the same case.
  { key: "subagents", label: "Subagents", render: (s) => (s.subagents > 0 ? String(s.subagents) : "—") },
  { key: "peak_context_tokens", label: "Peak ctx", render: (s) => formatTokens(s.peak_context_tokens) },
  { key: "peak_context_pct", label: "Peak %", render: (s) => formatPct(s.peak_context_pct) },
  { key: "output_tokens", label: "Output", render: (s) => formatTokens(s.output_tokens) },
  { key: "transcript_bytes", label: "Size", render: (s) => formatBytes(s.transcript_bytes) },
  // The churn pair sits beside the work columns rather than the token ones:
  // it measures what the session DID to the repo, not what it spent.
  { key: "files_touched", label: "Files", render: (s) => (s.files_touched > 0 ? String(s.files_touched) : "—") },
  { key: "lines", label: "Lines", render: churnCell },
  { key: "artifacts", label: "Artifacts", render: (s) => (s.artifacts > 0 ? String(s.artifacts) : "—") },
  { key: "cost_usd", label: "Cost", render: (s) => formatCostWithUnpriced(s.cost_usd, s.unpriced_turns) },
];

function sortSessions(rows: ChronicleSession[], key: SortKey, dir: "asc" | "desc"): ChronicleSession[] {
  const sign = dir === "asc" ? 1 : -1;
  const derived = key in SORT_VALUE ? SORT_VALUE[key as DerivedSortKey] : null;
  const valueOf = (s: ChronicleSession) =>
    derived ? derived(s) : s[key as RowSortKey] ?? -Infinity;
  return [...rows].sort((a, b) => {
    const av = valueOf(a);
    const bv = valueOf(b);
    return av === bv ? 0 : av > bv ? sign : -sign;
  });
}

export default function ChroniclePage({ summary, sessions, loading, error, onRetry, scope = "repo" }: ChroniclePageProps) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("started_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  // Table-local, unlike the window/scope/branch filters: those change what is
  // FETCHED (and so what every tile and chart above counts), while this only
  // narrows the rows already on screen. Keeping it here means toggling it can
  // never silently reshape the totals the reader just looked at.
  const [liveOnly, setLiveOnly] = useState(false);
  const [planFilter, setPlanFilter] = useState<string | null>(null);
  // Offered only across repos, and only when there is actually a split to
  // show — one plan is not a choice, it is a label.
  const planOptions = useMemo(() => plansPresent(sessions), [sessions]);
  const showPlanFilter = scope === "all" && planOptions.length > 1;
  // A filter left set while its control is hidden would silently narrow the
  // table with nothing on screen explaining why.
  const activePlan = showPlanFilter ? planFilter : null;
  const visible = useMemo(() => {
    let rows = liveOnly ? sessions.filter((s) => s.live) : sessions;
    if (activePlan) rows = rows.filter((s) => s.plan_organization_type === activePlan);
    return rows;
  }, [sessions, liveOnly, activePlan]);
  const liveCount = useMemo(() => sessions.filter((s) => s.live).length, [sessions]);
  const ordered = useMemo(() => sortSessions(visible, sortKey, sortDir), [visible, sortKey, sortDir]);
  const totals = summary?.totals ?? null;
  // The Counsel's four insights each walk the session list; recompute only
  // when the data does, not on every sort click or drawer open.
  const insights = useMemo(
    () =>
      totals
        ? windowInsights({
            totals,
            models: summary?.by_model ?? [],
            shape: summary?.shape ?? null,
            sessions,
            churn: summary?.churn,
            delegation: summary?.delegation,
          })
        : [],
    [totals, summary?.by_model, summary?.shape, sessions, summary?.churn, summary?.delegation]
  );
  // More than one Claude account in this window? Then the drawer names each
  // session's; otherwise the chip would say the same thing on every one.
  const multiAccount = useMemo(
    () => new Set(sessions.map((s) => s.config_dir).filter(Boolean)).size > 1,
    [sessions]
  );
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
  const costPerDay = byDay.map((d) => ({ label: formatDay(d.day), detail: d.day, value: d.cost_usd }));
  const churnPerDay = (summary?.churn?.by_day ?? []).map((d) => ({
    label: formatDay(d.day),
    detail: `${d.day} · +${d.lines_added} / -${d.lines_removed} · ${d.edits} edits`,
    value: d.lines_added + d.lines_removed,
  }));
  const shape = summary?.shape;
  const closeDrawer = useCallback(() => setOpenId(null), []);

  return (
    <div className={`chronicle${loading && summary ? " chronicle--refreshing" : ""}`}>
      {error && <Waylaid error={error} retryEverySeconds={CHRONICLE_RETRY_SECONDS} onRetry={onRetry} />}

      {summary && totals === null && (
        <div className="chronicle__empty">
          <p className="chronicle__empty-title">The chronicle is blank.</p>
          <p>Press <strong>Sync</strong> in the top bar to read every session transcript on this machine into it.</p>
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
            {/* Beside Sessions, not eight tiles down: these are the two
                population counts on the page — sessions started, and agents
                they delegated to. Split apart they read as unrelated trivia,
                which undersells the second: subagents outnumber sessions
                several times over and account for most of the Turns tile
                immediately to their right. */}
            <StatTile label="Subagents" value={String(totals.subagents)} hue="--chr-peak" />
            <StatTile label="Turns" value={formatTokens(totals.turns)} hue="--chr-turns" />
            <StatTile label="Tool calls" value={formatTokens(totals.tool_calls)} hue="--chr-tools" />
            <StatTile label="MCP calls" value={formatTokens(summary?.mcp?.calls ?? 0)} hue="--chr-tools" />
            <StatTile label="Plugin calls" value={formatTokens(summary?.plugins?.calls ?? 0)} hue="--chr-peak" />
            <StatTile
              label="Rework"
              value={churnRatio(summary?.churn?.lines_removed, summary?.churn?.lines_added)}
              note={`${formatTokens(summary?.churn?.lines_removed ?? 0)} undone`}
              hue="--chr-peak"
            />
            <StatTile
              label="Edits / file"
              value={perUnit(summary?.churn?.edits, summary?.churn?.files, 1)}
              note={`${formatTokens(summary?.churn?.edits ?? 0)} edits`}
              hue="--chr-tools"
            />
            <StatTile
              label="Output / line"
              value={perUnit(summary?.churn?.output_tokens,
                (summary?.churn?.lines_added ?? 0) + (summary?.churn?.lines_removed ?? 0), 0)}
              note="tokens written"
              hue="--chr-output"
            />
            <StatTile
              label="Lines / session"
              value={perUnit((summary?.churn?.lines_added ?? 0) + (summary?.churn?.lines_removed ?? 0),
                summary?.churn?.sessions, 0)}
              note={`over ${formatTokens(summary?.churn?.sessions ?? 0)} sessions`}
              hue="--chr-cache"
            />
            <StatTile
              label="Lines added"
              value={formatTokens(summary?.churn?.lines_added ?? 0)}
              note={`${formatTokens(summary?.churn?.files ?? 0)} files`}
              hue="--chr-cache"
            />
            <StatTile
              label="Lines removed"
              value={formatTokens(summary?.churn?.lines_removed ?? 0)}
              note={`${formatTokens(summary?.churn?.edits ?? 0)} edits`}
              hue="--chr-peak"
            />
            <StatTile
              label="Ctx processed"
              value={formatTokens(totals.input_tokens + totals.cache_read_tokens + totals.cache_creation_tokens)}
            />
            {/* The thinking share and the cache TTL split each get a ring
                below instead of a footnote here: a long note wrapped to two
                lines and threw every tile in its row out of height. */}
            <StatTile label="Output tokens" value={formatTokens(totals.output_tokens)} hue="--chr-output" />
            <StatTile label="Active time" value={formatActive(totals.active_ms)} hue="--chr-turns" />
            <StatTile
              label="Transcripts"
              value={formatBytes(totals.transcript_bytes)}
              hue="--chr-tools"
            />
            <StatTile label="Compactions" value={String(totals.compactions)} hue="--chr-peak" />
            <StatTile
              label="Cache written"
              value={formatTokens(totals.cache_creation_tokens)}
              hue="--chr-cache"
            />
            <StatTile label="Artifacts" value={String(totals.artifacts)} hue="--chr-output" />
            <StatTile
              label="API costs"
              value={formatCostWithUnpriced(totals.cost_usd, totals.unpriced_turns)}
              labelInfo={`API-equivalent cost at Anthropic's list prices as of ${formatMonth(totals.pricing_as_of)} — a comparison yardstick, not a bill. Most Claude Code use is a subscription with a usage limit rather than per-call billing, so this figure won't match an invoice.`}
              hue="--chr-cost"
            />
          </div>

          {/* Three fixed rows rather than one auto-fit flow: the panels pair
              up by what they answer — two rings and the money beside them,
              then the four per-day series, then the four ranked lists — and
              an auto-fit grid reflowed them into whatever the viewport
              allowed, splitting those groups at arbitrary widths. Each row
              collapses 3/4-up → 2-up → 1-up on its own. */}
          <div className="chronicle__grid chronicle__grid--wide">
            <CounselPanel insights={insights} />
          </div>

          <div className="chronicle__grid chronicle__grid--4">
            <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-output)" }}>
              <h3 className="chr-panel__title">Where output went</h3>
              <p className="chr-panel__sub">Tokens the model wrote: thinking versus replies and tool calls.</p>
              <Donut
                segments={[
                  { label: "Thinking", value: totals.thinking_tokens },
                  { label: "Replies & tools", value: Math.max(0, totals.output_tokens - totals.thinking_tokens) },
                ]}
                format={formatTokens}
                title="Where output went"
                centre={{ value: formatTokens(totals.output_tokens), label: "output" }}
                hue="--chr-output"
              />
            </section>
            <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-cache)" }}>
              <h3 className="chr-panel__title">Cache written by TTL</h3>
              <p className="chr-panel__sub">Prompt cache written this window, by how long it was kept.</p>
              <Donut
                segments={[
                  { label: "1h cache", value: totals.cache_1h_tokens },
                  { label: "5m cache", value: totals.cache_5m_tokens },
                  ...(totals.cache_creation_tokens - totals.cache_1h_tokens - totals.cache_5m_tokens > 0
                    ? [{ label: "Unlabelled", value: totals.cache_creation_tokens - totals.cache_1h_tokens - totals.cache_5m_tokens }]
                    : []),
                ]}
                format={formatTokens}
                title="Cache written by TTL"
                centre={{ value: formatTokens(totals.cache_creation_tokens), label: "written" }}
                hue="--chr-cache"
              />
            </section>
            <section className="chr-panel">
              <h3 className="chr-panel__title">Cost per day</h3>
              <p className="chr-panel__sub">What each day's calls would cost at API list prices.</p>
              <ColumnChart points={costPerDay} format={formatUsd} title="API-equivalent cost per day" hue="--chr-cost" />
            </section>
          </div>

          <div className="chronicle__grid chronicle__grid--4">
            <section className="chr-panel">
              <h3 className="chr-panel__title">Turns by model</h3>
              {/* The prompt count lives here, not on the Turns tile: the
                  tile grid is full, and a prompt only means something
                  next to the turns it spawned. */}
              <p className="chr-panel__sub">
                {formatTokens(totals.turns)} turns from {formatTokens(totals.prompts)} prompts
                {totals.prompts > 0 && ` · about ${Math.round(totals.turns / totals.prompts)} turns per prompt`}
              </p>
              <BarList
                rows={(summary?.by_model ?? []).map((m) => ({
                  label: shortModel(m.model),
                  detail: `${m.model} · ${m.sessions} sessions · ${formatTokens(m.output_tokens)} output · ${m.cost_usd === null ? "unpriced" : formatUsd(m.cost_usd)}`,
                  value: m.turns,
                }))}
                format={formatTokens}
                title="Turns by model"
                hue="--chr-turns"
              />
            </section>
          </div>

          <div className="chronicle__grid chronicle__grid--4">
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
              <h3 className="chr-panel__title">Lines changed per day</h3>
              <p className="chr-panel__sub">Added plus removed — editing done, not lines surviving.</p>
              <ColumnChart points={churnPerDay} format={formatTokens} title="Lines changed per day" hue="--chr-peak" />
            </section>
          </div>

          {/* One box, three grains — see UsageCallout. Full width because
              these lists are the only place on the page where the LABEL is
              the datum, and a quarter-width panel clipped `claude_ai_Notion`
              to `claude_ai_N…`. */}
          <div className="chronicle__grid chronicle__grid--2">
            <DelegationPanel delegation={summary?.delegation} />
            <CostAttributionPanel attribution={summary?.attribution} />
          </div>

          <div className="chronicle__grid chronicle__grid--wide">
            <UsageCallout
              tools={summary?.tools}
              mcp={summary?.mcp}
              plugins={summary?.plugins}
              churn={summary?.churn}
              contextGrowth={summary?.context_growth}
              attribution={summary?.attribution}
            />
          </div>

          {/* One grain below the callout's MCP tab, in its own box: which of
              a server's tools were called, and what each cost. */}
          <div className="chronicle__grid chronicle__grid--wide">
            <McpExplorer mcp={summary?.mcp} />
          </div>

          <div className="chronicle__grid chronicle__grid--wide">
            <section className="chr-panel chr-panel--wide" style={{ ["--chr-hue" as string]: "var(--chr-output)" }}>
              <h3 className="chr-panel__title">Artifacts</h3>
              <p className="chr-panel__sub">Pages published from these sessions, newest first.</p>
              <ArtifactList
                artifacts={(summary?.artifacts ?? []).slice(0, 12)}
                showSession
                onOpenSession={setOpenId}
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
                        ["Cost", shape.cost_usd, formatUsd],
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
            <div className="chr-panel__head">
              <h3 className="chr-panel__title">Sessions</h3>
              {/* Reuses the filter bar's segment styling so it reads as a
                  filter rather than as a table control of its own invention.
                  Disabled with nothing live: an enabled toggle that can only
                  ever empty the table is a trap. */}
              <div className="chronicle__segment" role="group" aria-label="Session activity">
                <Button
                  aria-pressed={!liveOnly}
                  onClick={() => setLiveOnly(false)}
                  className="chronicle__seg-btn"
                >
                  All
                </Button>
                <Button
                  aria-pressed={liveOnly}
                  onClick={() => setLiveOnly(true)}
                  disabled={liveCount === 0}
                  className="chronicle__seg-btn"
                >
                  {liveCount > 0 ? `Live (${liveCount})` : "Live"}
                </Button>
              </div>
              {showPlanFilter && (
                <div className="chronicle__segment" role="group" aria-label="Plan">
                  <Button
                    aria-pressed={activePlan === null}
                    onClick={() => setPlanFilter(null)}
                    className="chronicle__seg-btn"
                  >
                    All plans
                  </Button>
                  {planOptions.map((p) => (
                    <Button
                      key={p.plan}
                      aria-pressed={activePlan === p.plan}
                      onClick={() => setPlanFilter(p.plan)}
                      className="chronicle__seg-btn"
                    >
                      {`${p.label} (${p.count})`}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            {ordered.length === 0 ? (
              <p className="chr-chart__empty">
                {activePlan
                  ? `No ${planLabel(activePlan)} sessions${liveOnly ? " live right now" : " in this window"}.`
                  : liveOnly
                    ? "No live sessions right now."
                    : "No sessions in this window."}
              </p>
            ) : (
              <>
                <p className="chr-table__scroll-hint">Scroll sideways for more columns →</p>
                <div className="chr-table-wrap">
                  <table className="chr-table chr-table--sessions" aria-label="Sessions">
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
                          {/* Only ever rendered for a KNOWN plan — an unknown
                              one shows nothing at all, never the word. */}
                          {planLabel(s.plan_organization_type) && (
                            <span className="chr-plan">{planLabel(s.plan_organization_type)}</span>
                          )}
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
              </>
            )}
          </section>
        </>
      )}

      {summary === null && !error && <p className="board-placeholder">Loading chronicle…</p>}

      <SessionDrawer sessionId={openId} onClose={closeDrawer} showAccount={multiAccount} />
    </div>
  );
}
