import { useState } from "react";

import { formatTokens } from "../../board/chronicle/format";
import type { ChronicleMcp, ChroniclePlugins, ChronicleTool } from "../../api/types";
import { Button } from "../../ui";
import { BarList } from "./ChronicleCharts";

type View = "tools" | "mcp" | "plugins";

interface UsageCalloutProps {
  tools?: ChronicleTool[];
  mcp?: ChronicleMcp;
  plugins?: ChroniclePlugins;
  /** Per-session copy drops the "across N sessions" clauses, which would all
   * read "across 1 sessions" in the drawer. */
  perSession?: boolean;
}

interface Row {
  label: string;
  value: number;
  detail?: string;
}

/**
 * The three "what did it call" breakdowns — every tool, MCP by server, and
 * plugins — in ONE full-width box behind a segmented switch.
 *
 * They were three panels in a four-up row, and the row was the problem: a
 * quarter-width panel gives `.chr-barlist__row` a ~90px label column, so
 * `claude_ai_Notion` rendered as `claude_ai_N…`. These lists are the one
 * place on the page where the LABEL carries the meaning — a server, a plugin,
 * a tool — and a truncated one is worth nothing. Full width restores about
 * 360px to it.
 *
 * A switch rather than three stacked lists because they answer the same
 * question at three grains, so they are read one at a time and compared
 * against each other, never scanned together.
 */
export default function UsageCallout({ tools, mcp, plugins, perSession }: UsageCalloutProps) {
  const [view, setView] = useState<View>("tools");

  const sessionsOf = (n: number | undefined) =>
    perSession || n === undefined ? "" : ` across ${n} ${n === 1 ? "session" : "sessions"}`;

  const toolRows: Row[] = (tools ?? []).slice(0, 12).map((t) => ({
    label: t.tool_name,
    detail: `${t.calls} calls${sessionsOf(t.sessions)}`,
    value: t.calls,
  }));

  const mcpRows: Row[] = (mcp?.servers ?? []).slice(0, 12).map((s) => ({
    label: s.server,
    detail: `${s.provenance} · ${s.tools} tools · ${s.calls} calls${sessionsOf(s.sessions)}`,
    value: s.calls,
  }));

  const pluginRows: Row[] = (plugins?.items ?? []).slice(0, 12).map((p) => ({
    label: `${p.plugin} · ${p.kind}`,
    detail: `${p.calls} calls${sessionsOf(p.sessions)}`,
    value: p.calls,
  }));

  const provenance = mcp?.by_provenance ?? {};
  const provenanceNote = ["plugin", "connector", "local"]
    .filter((k) => provenance[k])
    .map((k) => `${provenance[k]} ${k}`)
    .join(" · ");

  const views: { key: View; label: string; count: number; rows: Row[]; hue: string;
                 sub: string; empty: string }[] = [
    {
      key: "tools",
      label: "Tools",
      count: tools?.reduce((n, t) => n + t.calls, 0) ?? 0,
      rows: toolRows,
      hue: "--chr-tools",
      sub: "Every tool call, most-used first.",
      empty: "No tool calls in this window.",
    },
    {
      key: "mcp",
      label: "MCP",
      count: mcp?.calls ?? 0,
      rows: mcpRows,
      hue: "--chr-context",
      sub: provenanceNote
        ? `By server — ${provenanceNote}.`
        : "By server, split into plugin, connector and local.",
      empty: "No MCP calls in this window.",
    },
    {
      key: "plugins",
      label: "Plugins",
      count: plugins?.calls ?? 0,
      rows: pluginRows,
      hue: "--chr-peak",
      // Names the overlap rather than letting the two tabs look inconsistent.
      sub: "Plugin-provided MCP servers and plugin skills. A plugin's MCP calls are counted on the MCP tab too.",
      empty: "No plugin usage recorded. Historical sessions need a `chronicle sync --full` to backfill.",
    },
  ];

  const active = views.find((v) => v.key === view) ?? views[0];

  return (
    <section
      className="chr-panel chr-panel--wide"
      style={{ ["--chr-hue" as string]: `var(${active.hue})` }}
    >
      <div className="chr-panel__head">
        <h3 className="chr-panel__title">Usage breakdown</h3>
        <div className="chronicle__segment" role="group" aria-label="Usage breakdown">
          {views.map((v) => (
            <Button
              key={v.key}
              aria-pressed={view === v.key}
              onClick={() => setView(v.key)}
              className="chronicle__seg-btn"
            >
              {v.label} {formatTokens(v.count)}
            </Button>
          ))}
        </div>
      </div>
      <p className="chr-panel__sub">{active.sub}</p>
      {active.rows.length === 0 ? (
        <p className="chr-chart__empty">{active.empty}</p>
      ) : (
        <BarList
          rows={active.rows}
          format={formatTokens}
          title={`${active.label} breakdown`}
          hue={active.hue}
        />
      )}
    </section>
  );
}
