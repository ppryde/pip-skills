/**
 * One session in detail — the Chronicle's counterpart to CardDetailDrawer,
 * and it reuses that drawer's shell classes (`.drawer-overlay`,
 * `.card-drawer`) so the two sheets read as one family. Page-local state
 * (ChroniclePage owns `openId`); Escape and the backdrop close it.
 */
import { useEffect } from "react";
import { useChronicleSession } from "../../board/chronicle/useChronicle";
import {
  cacheVerdict,
  formatActive,
  formatBytes,
  formatCostWithUnpriced,
  formatDuration,
  formatPct,
  formatTokens,
  formatWhen,
  repoLabel,
  sessionName,
  shortModel,
} from "../../board/chronicle/format";
import ArtifactList from "./ArtifactList";
import { BarList, LineChart } from "./ChronicleCharts";
import type { ChartEvent } from "./ChronicleCharts";
import Gauge from "./Gauge";
import StatTile from "./StatTile";

export interface SessionDrawerProps {
  sessionId: string | null;
  onClose: () => void;
}

/** A gap between turns worth naming in the tooltip — on a 5-minute cache
 * TTL, long enough to have gone cold. */
const IDLE_GAP_S = 300;
/** How many of the biggest jumps get a peak glyph on the chart — the single
 * largest; the table beneath lists the rest. */
const JUMPS_MARKED = 1;

export default function SessionDrawer({ sessionId, onClose }: SessionDrawerProps) {
  const { detail, loading, error } = useChronicleSession(sessionId);

  useEffect(() => {
    if (sessionId === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sessionId, onClose]);

  if (sessionId === null) return null;

  const contextSeries = detail?.turn_series.map((t) => t.context_tokens) ?? [];
  const annotate = (i: number): string | null => {
    const turn = detail?.turn_series[i];
    if (!turn) return null;
    const parts: string[] = [];
    if (turn.cold) parts.push(`wrote ${formatTokens(turn.cache_creation_tokens)} to cache`);
    if (turn.gap_s !== null && turn.gap_s >= IDLE_GAP_S) parts.push(`idle ${formatDuration(turn.gap_s)}`);
    return parts.length > 0 ? parts.join(" · ") : null;
  };
  // The chart's marks: every cold turn (idle gaps stay in the tooltip — a
  // mark for them was tried and read as noise); the single biggest jump;
  // and each compaction placed at the first turn at or after its timestamp
  // so the hairline lands where the context actually dropped.
  const events: ChartEvent[] = detail
    ? [
        ...detail.turn_series.flatMap((t, i): ChartEvent[] => (t.cold ? [{ index: i, kind: "cold" }] : [])),
        ...detail.biggest_jumps.slice(0, JUMPS_MARKED).map((j): ChartEvent => ({ index: j.turn - 1, kind: "jump" })),
        ...detail.compactions_at
          .map((ts) => detail.turn_series.findIndex((t) => (t.ts ?? 0) >= ts))
          .filter((i) => i >= 0)
          .map((index): ChartEvent => ({ index, kind: "compaction" })),
      ]
    : [];

  return (
    <div className="drawer-overlay" data-testid="chronicle-drawer-overlay" onClick={onClose}>
      <aside
        className="card-drawer chr-drawer"
        role="dialog"
        aria-label={detail ? `${sessionName(detail)} session` : "Session details"}
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className="card-drawer__close" onClick={onClose} aria-label="Close">
          ×
        </button>
        {loading && !detail && <p className="card-drawer__status">Loading…</p>}
        {error && <p className="card-drawer__status card-drawer__status--error">{error}</p>}
        {detail && (
          <>
            <header className="chr-drawer__header">
              <p className="chr-drawer__eyebrow">
                <span className="chr-mono">{detail.session_id}</span>
                {detail.live && <span className="chr-live" title="Active in the last 15 minutes">live</span>}
              </p>
              <h2 className="chr-drawer__title">{sessionName(detail)}</h2>
              <p className="chr-drawer__facts">
                <span>{repoLabel(detail.repo_root)}</span>
                {detail.git_branch && <span className="chr-mono">{detail.git_branch}</span>}
                {/* Multi-account: which Claude config dir this session ran
                    under, by its folder name (".claude-personal"). */}
                {detail.config_dir && (
                  <span className="chr-chip" title={detail.config_dir}>
                    {detail.config_dir.split("/").filter(Boolean).pop()}
                  </span>
                )}
                {detail.models.map((m) => (
                  <span key={m} className="chr-chip">
                    {shortModel(m)}
                  </span>
                ))}
              </p>
              <p className="chr-drawer__facts chr-drawer__facts--muted">
                <span>started {formatWhen(detail.started_at)}</span>
                <span>last {formatWhen(detail.last_activity_at)}</span>
                {detail.end_reason && <span>ended: {detail.end_reason}</span>}
                {detail.version && <span>cc {detail.version}</span>}
              </p>
            </header>

            <div className="chr-hero chr-hero--drawer">
              <Gauge
                value={detail.cache_hit_rate}
                display={formatPct(detail.cache_hit_rate)}
                label="Cache hit rate"
                verdict={cacheVerdict(detail.cache_hit_rate)}
                note={`${detail.cold_turns} cold turns`}
                hue="--chr-cache"
              />
              <Gauge
                value={detail.peak_context_pct}
                display={formatPct(detail.peak_context_pct)}
                label="Peak context used"
                verdict={`${formatTokens(detail.peak_context_tokens)} of ${formatTokens(detail.context_window)}`}
                hue="--chr-peak"
              />
            </div>

            <div className="chr-tiles chr-tiles--drawer">
              <StatTile label="Turns" value={String(detail.turns)} hue="--chr-turns" />
              <StatTile label="Prompts" value={String(detail.prompts)} hue="--chr-turns" />
              <StatTile label="Tool calls" value={String(detail.tool_calls)} hue="--chr-tools" />
              <StatTile label="Output tokens" value={formatTokens(detail.output_tokens)} hue="--chr-output" />
              <StatTile label="Total ctx" value={formatTokens(detail.context_tokens)} />
              <StatTile label="Span" value={formatDuration(detail.duration_s)} />
              <StatTile label="Active" value={formatActive(detail.active_ms)} />
              <StatTile label="Transcript" value={formatBytes(detail.transcript_bytes)} hue="--chr-tools" />
              <StatTile label="Compactions" value={String(detail.compactions)} hue="--chr-peak" />
              <StatTile
                label="Cache written"
                value={formatTokens(detail.cache_creation_tokens)}
                hue="--chr-cache"
              />
              <StatTile
                label="API costs"
                value={formatCostWithUnpriced(detail.cost_usd, detail.unpriced_turns)}
                labelInfo="API-equivalent cost: what these calls would cost at Anthropic's list prices — a comparison yardstick, not a bill. Most Claude Code use is a subscription with a usage limit rather than per-call billing, so this figure won't match an invoice."
                hue="--chr-cost"
              />
            </div>

            <section className="chr-panel">
              <h3 className="chr-panel__title">Context per turn</h3>
              <p className="chr-panel__sub">Tokens in the window on each API call; the marks are explained below the plot.</p>
              <LineChart
                values={contextSeries}
                format={formatTokens}
                title="Context tokens per turn"
                events={events}
                annotate={annotate}
                tableColumn={{
                  heading: "Since last turn",
                  cell: (i) => {
                    const gap = detail.turn_series[i]?.gap_s;
                    return gap === null || gap === undefined ? null : formatDuration(gap);
                  },
                }}
                hue="--chr-context"
              />
            </section>

            <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-peak)" }}>
              <h3 className="chr-panel__title">Biggest jumps</h3>
              <p className="chr-panel__sub">
                Turns whose context grew most since the one before, and what landed in between.
              </p>
              {detail.biggest_jumps.length === 0 ? (
                <p className="chr-chart__empty">No turns recorded.</p>
              ) : (
                <table className="chr-table chr-table--compact" aria-label="Biggest jumps">
                  <thead>
                    <tr>
                      <th scope="col">Turn</th>
                      <th scope="col" className="chr-num">Jump</th>
                      <th scope="col" className="chr-num">Context</th>
                      <th scope="col">What landed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.biggest_jumps.map((j) => (
                      <tr key={j.turn}>
                        <td>
                          {j.turn}
                          {j.cold && <span className="chr-live chr-live--cold">cold</span>}
                        </td>
                        <td className="chr-num">+{formatTokens(j.delta_tokens)}</td>
                        <td className="chr-num">{formatTokens(j.context_tokens)}</td>
                        <td className="chr-table__landed">
                          {j.landed.length === 0
                            ? (j.output_tokens > 0 ? `model wrote ${formatTokens(j.output_tokens)}` : "—")
                            : j.landed.map((l) => `${l.tool_name} ${formatTokens(l.chars)} chars`).join(" · ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            {detail.artifacts.length > 0 && (
              <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-output)" }}>
                <h3 className="chr-panel__title">Artifacts</h3>
                <ArtifactList artifacts={detail.artifacts} />
              </section>
            )}

            <section className="chr-panel">
              <h3 className="chr-panel__title">Tools</h3>
              <BarList
                rows={detail.tools.slice(0, 12).map((t) => ({ label: t.tool_name, value: t.calls }))}
                format={(n) => String(n)}
                title="Tool calls in this session"
                hue="--chr-tools"
              />
            </section>

            {detail.subagents.length > 0 && (
              <section className="chr-panel">
                <h3 className="chr-panel__title">Subagents</h3>
                <table className="chr-table chr-table--compact">
                  <thead>
                    <tr>
                      <th scope="col">Agent</th>
                      <th scope="col" className="chr-num">Turns</th>
                      <th scope="col" className="chr-num">Context</th>
                      <th scope="col" className="chr-num">Output</th>
                      <th scope="col" className="chr-num">Tools</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.subagents.map((a) => (
                      <tr key={a.agent_id}>
                        <td className="chr-mono">{a.agent_id.replace(/^a/, "").split("-").slice(0, -1).join("-") || a.agent_id}</td>
                        <td className="chr-num">{a.turns}</td>
                        <td className="chr-num">{formatTokens(a.context_tokens)}</td>
                        <td className="chr-num">{formatTokens(a.output_tokens)}</td>
                        <td className="chr-num">{a.tool_calls}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
