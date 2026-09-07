import { useState } from "react";

import { formatBytes, formatDuration, formatTokens } from "../../board/chronicle/format";
import type { ChronicleChurn, ChronicleMcp, ChroniclePlugins, ChronicleTool } from "../../api/types";
import { Button } from "../../ui";
import { BarList } from "./ChronicleCharts";

type View = "tools" | "mcp" | "plugins" | "files";

interface UsageCalloutProps {
  tools?: ChronicleTool[];
  mcp?: ChronicleMcp;
  plugins?: ChroniclePlugins;
  churn?: ChronicleChurn;
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
export default function UsageCallout({ tools, mcp, plugins, churn, perSession }: UsageCalloutProps) {
  const [view, setView] = useState<View>("tools");

  const sessionsOf = (n: number | undefined) =>
    perSession || n === undefined ? "" : ` across ${n} ${n === 1 ? "session" : "sessions"}`;

  /** The three measures every bucket carries, as one line. Only what is
   * actually known: a bucket whose calls never landed a result has no median,
   * and saying "0s" there would be a different claim from "we don't know". */
  const measures = (u: {
    calls: number; result_chars?: number; median_s?: number | null; subagent_calls?: number;
    sessions?: number;
  }) =>
    [
      `${u.calls} calls${sessionsOf(u.sessions)}`,
      u.result_chars ? `${formatBytes(u.result_chars)} returned` : null,
      u.median_s != null ? `${formatDuration(u.median_s)} typical` : null,
      u.subagent_calls
        ? `${Math.round((u.subagent_calls / u.calls) * 100)}% delegated`
        : null,
    ]
      .filter(Boolean)
      .join(" · ");

  // No slicing: the list scrolls instead, so a long tail stays reachable
  // rather than being silently cut at an arbitrary twelve.
  const toolRows: Row[] = (tools ?? []).map((t) => ({
    label: t.tool_name,
    detail: measures(t),
    value: t.calls,
  }));

  const mcpRows: Row[] = (mcp?.servers ?? []).map((s) => ({
    label: s.server,
    detail: `${s.provenance} · ${s.tools} tools · ${measures(s)}`,
    value: s.calls,
  }));

  const pluginRows: Row[] = (plugins?.items ?? []).map((p) => ({
    label: `${p.plugin} · ${p.kind}`,
    detail: measures(p),
    value: p.calls,
  }));

  // Ranked by total churn, so the file that moved most is first — the value
  // is added+removed, since a big deletion is as much editing as a big
  // addition.
  const fileRows: Row[] = (churn?.files_by_churn ?? []).map((f) => ({
    label: f.file_path.split("/").slice(-2).join("/"),
    detail: `${f.file_path} — ${f.edits} edits · +${f.lines_added} / -${f.lines_removed}`
      + (f.operations.includes("create") ? " · created here" : "")
      + sessionsOf(f.sessions),
    value: f.lines_added + f.lines_removed,
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
    {
      key: "files",
      label: "Files",
      count: churn?.files ?? 0,
      rows: fileRows,
      hue: "--chr-cache",
      sub: churn
        ? `+${churn.lines_added.toLocaleString()} / -${churn.lines_removed.toLocaleString()} across `
          + `${churn.edits.toLocaleString()} edits. Editing done, not lines surviving — a reverted `
          + `change still counts, so git is the source for what shipped.`
        : "Files changed, ranked by how much moved.",
      empty: "No file changes recorded. Historical sessions need a `chronicle sync --full` to backfill.",
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
        {/* Each tab wears its own measure's hue, pressed or not, so the
            three read as a switch rather than as one button with two greyed
            neighbours — the previous look, which hid that they were even
            selectable. The pressed one fills; the others keep the hue as a
            border and text only. */}
        <div className="chr-usage__tabs" role="group" aria-label="Usage breakdown">
          {views.map((v) => (
            <Button
              key={v.key}
              aria-pressed={view === v.key}
              onClick={() => setView(v.key)}
              className="chr-usage__tab"
              style={{ ["--chr-hue" as string]: `var(${v.hue})` }}
            >
              {v.label} <span className="chr-usage__count">{formatTokens(v.count)}</span>
            </Button>
          ))}
        </div>
      </div>
      <p className="chr-panel__sub">{active.sub}</p>
      {active.rows.length === 0 ? (
        <p className="chr-chart__empty">{active.empty}</p>
      ) : (
        <div className="chr-usage__scroll">
          <BarList
            rows={active.rows}
            format={formatTokens}
            title={`${active.label} breakdown`}
            hue={active.hue}
          />
        </div>
      )}
    </section>
  );
}
