/**
 * One subagent in detail — a second sheet layered over `SessionDrawer`,
 * with a rail on the left to move between the session's agents or go back.
 *
 * Layered rather than replacing, because a subagent is only ever read IN the
 * context of the session that spawned it: "which of these eight agents spent
 * the tokens" is a comparison, and a drawer you have to close and reopen to
 * make it is the wrong shape. The rail keeps the comparison one click wide.
 *
 * The rail's label is the task the agent was handed, lifted from the first
 * prompt of its own transcript — an agent's id is a hash, so without it the
 * list reads `a8905de978ab95a89` eight times. That text is UNTRUSTED
 * transcript content and renders as a text node only, never as markup.
 */
import { useEffect } from "react";

import { useChronicleAgent } from "../../board/chronicle/useChronicle";
import {
  cacheVerdict,
  formatCostWithUnpriced,
  formatDuration,
  formatPct,
  formatTokens,
  formatWhen,
} from "../../board/chronicle/format";
import type { ChronicleSubagent } from "../../api/types";
import ArtifactList from "./ArtifactList";
import { LineChart } from "./ChronicleCharts";
import type { ChartEvent } from "./ChronicleCharts";
import Gauge from "./Gauge";
import StatTile from "./StatTile";
import McpExplorer from "./McpExplorer";
import UsageCallout from "./UsageCallout";

export interface SubagentDrawerProps {
  sessionId: string;
  /** The session's agents, in the order the session drawer lists them. */
  agents: ChronicleSubagent[];
  agentId: string;
  /** Move to another agent without leaving this layer. */
  onSelect: (agentId: string) => void;
  /** Close this layer, leaving the session drawer beneath it open. */
  onBack: () => void;
  /** What the back control names — the session this agent belongs to. */
  sessionLabel: string;
}

/** An agent id is a 17-character hash; the leading `a` is a prefix every one
 * of them carries, so it says nothing. Enough of the rest to tell two apart. */
export function shortAgent(agentId: string): string {
  return agentId.replace(/^a/, "").slice(0, 8);
}

/** The rail's label: the task if the store has one, else the id. Never a
 * fabricated summary — an unnamed agent says so by showing its id. */
export function agentLabel(agent: ChronicleSubagent): string {
  // `description` first: Claude Code writes a three-to-five word summary for
  // almost every agent, and it is a NAME. `task` is the opening prompt —
  // 1,200 to 3,500 characters — which as a label truncates into a mangled
  // paragraph and dictates the width of the column it sits in. It stays as
  // the fallback for agents with no meta file, and for a store not yet
  // resynced with `--full`.
  return agent.description ?? agent.task ?? shortAgent(agent.agent_id);
}

export default function SubagentDrawer({
  sessionId, agents, agentId, onSelect, onBack, sessionLabel,
}: SubagentDrawerProps) {
  const { detail, loading, error } = useChronicleAgent(sessionId, agentId);
  const current = agents.find((a) => a.agent_id === agentId);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      // Only the top layer closes, and the session drawer beneath must not
      // also act on the same press — hence stopPropagation on the container
      // below plus this capture-phase handler taking the event first.
      e.stopPropagation();
      onBack();
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onBack]);

  const events: ChartEvent[] = detail
    ? detail.turn_series.flatMap((t, i): ChartEvent[] => (t.cold ? [{ index: i, kind: "cold" }] : []))
    : [];

  return (
    <div className="drawer-overlay drawer-overlay--stacked" data-testid="subagent-drawer-overlay"
         onClick={onBack}>
      <aside
        className="card-drawer chr-drawer chr-drawer--agent"
        role="dialog"
        aria-label={current ? `${agentLabel(current)} subagent` : "Subagent details"}
        onClick={(e) => e.stopPropagation()}
      >
        <nav className="chr-rail" aria-label="Subagents">
          <button type="button" className="chr-rail__back" onClick={onBack}>
            <span aria-hidden="true">←</span> {sessionLabel}
          </button>
          <p className="chr-rail__count">
            {agents.length} {agents.length === 1 ? "subagent" : "subagents"}
          </p>
          <ul className="chr-rail__list">
            {agents.map((a) => (
              <li key={a.agent_id}>
                <button
                  type="button"
                  className="chr-rail__item"
                  aria-current={a.agent_id === agentId ? "true" : undefined}
                  onClick={() => onSelect(a.agent_id)}
                >
                  <span className="chr-rail__type">{a.agent_type ?? "subagent"}</span>
                  <span className="chr-rail__task">{agentLabel(a)}</span>
                  <span className="chr-rail__meta">
                    {a.turns} turns · {formatTokens(a.output_tokens)} out
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="chr-drawer__pane">
          {loading && !detail && <p className="card-drawer__status">Loading…</p>}
          {error && <p className="card-drawer__status card-drawer__status--error">{error}</p>}
          {detail && (
            <>
              <header className="chr-drawer__header">
                <p className="chr-drawer__eyebrow">
                  <span className="chr-mono">{detail.agent_id}</span>
                  {detail.agent_type && <span className="chr-chip">{detail.agent_type}</span>}
                </p>
                {/* The task, in full rather than the rail's one line — it is
                    the whole of what this agent was asked to do. */}
                <h2 className="chr-drawer__title chr-drawer__title--task">
                  {detail.task ?? shortAgent(detail.agent_id)}
                </h2>
                <p className="chr-drawer__facts chr-drawer__facts--muted">
                  <span>started {formatWhen(detail.first_ts)}</span>
                  <span>last {formatWhen(detail.last_ts)}</span>
                </p>
              </header>

              <div className="chr-hero chr-hero--drawer">
                <Gauge
                  value={detail.cache_hit_rate}
                  display={formatPct(detail.cache_hit_rate)}
                  label="Cache hit rate"
                  verdict={cacheVerdict(detail.cache_hit_rate)}
                  hue="--chr-cache"
                />
                <Gauge
                  value={null}
                  display={formatTokens(detail.peak_context_tokens)}
                  label="Peak context"
                  verdict={`${detail.turns} turns`}
                  hue="--chr-peak"
                />
              </div>

              <div className="chr-tiles chr-tiles--drawer">
                <StatTile label="Turns" value={String(detail.turns)} hue="--chr-turns" />
                <StatTile label="Tool calls" value={String(detail.tool_calls)} hue="--chr-tools" />
                <StatTile label="Output tokens" value={formatTokens(detail.output_tokens)} hue="--chr-output" />
                <StatTile label="Total ctx" value={formatTokens(detail.context_tokens)} />
                <StatTile label="Span" value={formatDuration(detail.duration_s)} />
                <StatTile
                  label="API costs"
                  value={formatCostWithUnpriced(detail.cost_usd, detail.unpriced_turns)}
                  labelInfo="API-equivalent cost of this agent's turns at Anthropic's list prices — a comparison yardstick, not a bill."
                  hue="--chr-cost"
                />
                {detail.churn && detail.churn.files > 0 && (
                  <StatTile label="Files touched" value={String(detail.churn.files)} hue="--chr-cache" />
                )}
                {detail.churn && (detail.churn.lines_added > 0 || detail.churn.lines_removed > 0) && (
                  <StatTile
                    label="Lines"
                    value={`+${detail.churn.lines_added.toLocaleString()} / -${detail.churn.lines_removed.toLocaleString()}`}
                    hue="--chr-cache"
                  />
                )}
              </div>

              <section className="chr-panel">
                <h3 className="chr-panel__title">Context per turn</h3>
                <p className="chr-panel__sub">
                  This agent's own calls. A subagent starts cold by design — it is a fresh
                  window, so the first turn writes the cache rather than reading it.
                </p>
                <LineChart
                  values={detail.turn_series.map((t) => t.context_tokens)}
                  format={formatTokens}
                  title="Context tokens per turn"
                  events={events}
                  hue="--chr-context"
                />
              </section>

              {detail.artifacts.length > 0 && (
                <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-output)" }}>
                  <h3 className="chr-panel__title">Artifacts</h3>
                  <ArtifactList artifacts={detail.artifacts} />
                </section>
              )}

              <UsageCallout
                tools={detail.tools}
                mcp={detail.mcp}
                plugins={detail.plugins}
                churn={detail.churn}
                contextGrowth={detail.context_growth}
                perSession
              />

              <McpExplorer mcp={detail.mcp} perSession />
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
