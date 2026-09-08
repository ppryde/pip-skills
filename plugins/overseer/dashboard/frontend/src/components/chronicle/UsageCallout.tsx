import { useState } from "react";

import { formatBytes, formatDuration, formatTokens, formatUsd } from "../../board/chronicle/format";
import { mcpServerNames, mcpToolLabel, parseMcpToolName } from "../../board/chronicle/mcp";
import type {
  ChronicleAttributed,
  ChronicleAttribution,
  ChronicleChurn,
  ChronicleContextGrowth,
  ChronicleMcp,
  ChroniclePlugins,
  ChronicleTool,
} from "../../api/types";
import { Button } from "../../ui";
import { BarList, type BarRow } from "./ChronicleCharts";

type View = "tools" | "context" | "mcp" | "plugins" | "skills" | "agents" | "files";

interface UsageCalloutProps {
  tools?: ChronicleTool[];
  mcp?: ChronicleMcp;
  plugins?: ChroniclePlugins;
  churn?: ChronicleChurn;
  contextGrowth?: ChronicleContextGrowth;
  attribution?: ChronicleAttribution;
  /** Per-session copy drops the "across N sessions" clauses, which would all
   * read "across 1 sessions" in the drawer. */
  perSession?: boolean;
}

type Row = BarRow;

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
export default function UsageCallout({
  tools, mcp, plugins, churn, contextGrowth, attribution, perSession,
}: UsageCalloutProps) {
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

  // The same join the MCP tab does, applied one grain lower: this list ranks
  // EVERY call, so an MCP one was still showing its raw
  // `mcp__claude_ai_Notion__fetch` slug beside a plain `Bash` long after the
  // server tab had learnt to say "claude.ai Notion". A non-MCP name is its
  // own label and passes through untouched.
  const names = mcpServerNames(mcp);

  // No slicing: the list scrolls instead, so a long tail stays reachable
  // rather than being silently cut at an arbitrary twelve.
  const toolRows: Row[] = (tools ?? []).map((t) => ({
    // The raw name is the key — two servers can own a `search`, and the
    // relabelled string is no longer guaranteed unique.
    id: t.tool_name,
    label: mcpToolLabel(t.tool_name, names),
    // The slug stays in the detail, as it does on the MCP tab: it is what
    // anyone grepping a transcript will actually be looking for.
    detail: [measures(t), parseMcpToolName(t.tool_name) ? t.tool_name : null]
      .filter(Boolean).join(" · "),
    value: t.calls,
  }));

  // The label is the server's REAL name where attribution recorded one —
  // "claude.ai Snowflake", not the `claude_ai_Snowflake` slug that the tool
  // name happens to spell it with. The slug is the row's key and stays in
  // the detail line, so nothing that has to be searched for is lost.
  const mcpRows: Row[] = (mcp?.servers ?? []).map((s) => ({
    id: s.server,
    label: s.name ?? s.server,
    detail: [
      s.provenance,
      `${s.tools} tools`,
      measures(s),
      s.name && s.name !== s.server ? s.server : null,
    ].filter(Boolean).join(" · "),
    value: s.calls,
  }));

  const pluginRows: Row[] = (plugins?.items ?? []).map((p) => ({
    label: `${p.plugin} · ${p.kind}`,
    detail: measures(p),
    value: p.calls,
  }));

  /** A share as a percentage, never rounded to a bare "0%": a tool at
   * 0.4% of a 300 MB window still poured in more than a megabyte, and "0%"
   * would say it poured in nothing. */
  const share = (s: number) =>
    s >= 0.1 ? `${Math.round(s * 100)}%`
      : s >= 0.001 ? `${(s * 100).toFixed(1)}%`
        : "<0.1%";

  // Ranked by what each tool RETURNED, which the backend already ordered —
  // re-sorting the `tools` block client-side would not do: that one truncates
  // at 50 BY CALLS, and the tools worth seeing here are exactly the ones
  // called rarely and returning enormously.
  const contextRows: Row[] = (contextGrowth?.tools ?? []).map((t) => ({
    label: t.tool_name,
    detail: [
      `${share(t.share)} of everything returned`,
      `${t.calls.toLocaleString()} calls`,
      t.avg_chars === null ? "no result sizes recorded" : `${formatBytes(t.avg_chars)} per call`,
      t.measured_calls < t.calls
        ? `${(t.calls - t.measured_calls).toLocaleString()} unmeasured`
        : null,
    ].filter(Boolean).join(" · "),
    value: t.result_chars,
  }));

  // Ranked by total churn, so the file that moved most is first — the value
  // is added+removed, since a big deletion is as much editing as a big
  // addition.
  const fileRows: Row[] = (churn?.files_by_churn ?? []).map((f) => ({
    // The path is the key: two files can share their last two segments
    // (three `src/styles.css` in this store), and duplicate keys strand rows.
    id: f.file_path,
    label: f.file_path.split("/").slice(-2).join("/"),
    detail: `${f.file_path} — ${f.edits} edits · +${f.lines_added} / -${f.lines_removed}`
      + (f.operations.includes("create") ? " · created here" : "")
      + sessionsOf(f.sessions),
    value: f.lines_added + f.lines_removed,
  }));

  /** An attributed bucket as a row: ranked by context tokens, because the
   * point of attribution is what a thing COST, not how often it ran. */
  const attributedRows = (items: ChronicleAttributed[] | undefined, label?: string): Row[] =>
    (items ?? []).map((a) => ({
      label: label ? `${a.name} · ${label}` : a.name,
      detail: [
        `${a.turns} turns`,
        `${formatTokens(a.context_tokens)} context`,
        `${formatTokens(a.output_tokens)} output`,
        a.cost_usd === null ? "unpriced" : formatUsd(a.cost_usd),
        a.skills ? `${a.skills} skills` : null,
        a.plugin ? `from ${a.plugin}` : null,
      ].filter(Boolean).join(" · ") + sessionsOf(a.sessions),
      value: a.context_tokens,
    }));

  const attributed = attribution?.plugins ?? [];
  const provenance = mcp?.by_provenance ?? {};
  const provenanceNote = ["plugin", "connector", "local"]
    .filter((k) => provenance[k])
    .map((k) => `${provenance[k]} ${k}`)
    .join(" · ");

  // `format` and `countLabel` default to the token formatter every other tab
  // wants; the Context tab overrides both because its measure is characters.
  const views: { key: View; label: string; count: number; rows: Row[]; hue: string;
                 sub: string; empty: string; format?: (n: number) => string;
                 countLabel?: string }[] = [
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
      // The companion to Tools, and the reason both exist: on this store Bash
      // tops the call count three to one over Read, and Read tops this by a
      // factor of two — because a Read averages ~11.7k characters against
      // Bash's ~1.4k. Neither list says that alone.
      key: "context",
      label: "Context",
      count: contextGrowth?.tools_total ?? 0,
      // Bytes, not tokens: this counts characters that entered the context,
      // and re-labelling them as tokens would be a 4x guess dressed as a
      // measurement.
      countLabel: contextGrowth ? formatBytes(contextGrowth.result_chars) : undefined,
      rows: contextRows,
      format: formatBytes,
      // The one hue not already spoken for. It is named for cost, but this
      // block measures VOLUME — see the sub-line: dollars are refused here on
      // purpose.
      hue: "--chr-cost",
      sub: contextGrowth
        ? `${formatBytes(contextGrowth.result_chars)} of tool results entered the context across `
          + `${contextGrowth.tools_total} tools. What a tool RETURNS is what every later turn `
          + `carries — so this ranks by volume returned, not by dollars: a turn's cost was paid `
          + `on the prompt it carried, before any of its tools ran.`
        : "Tools ranked by how much their results poured into the context.",
      empty: "No result sizes recorded. Historical sessions need a `chronicle sync --full` to backfill.",
    },
    {
      key: "mcp",
      label: "MCP",
      count: mcp?.calls ?? 0,
      rows: mcpRows,
      hue: "--chr-context",
      // Says where the next grain down lives: this tab stops at the server,
      // and someone reading it is one question away from wanting the tools.
      sub: (provenanceNote
        ? `By server — ${provenanceNote}.`
        : "By server, split into plugin, connector and local.")
        + (mcp?.tools?.length ? " Per-tool detail is in the MCP tools panel below." : ""),
      empty: "No MCP calls in this window.",
    },
    {
      // Attribution when the store has it: Claude Code stamps the plugin in
      // scope onto every TURN, so this is what a plugin COST, not how often
      // it was invoked. Falls back to the call counts for a store that has
      // not been resynced since the columns landed.
      key: "plugins",
      label: "Plugins",
      count: attributed.length ? attributed.length : (plugins?.calls ?? 0),
      rows: attributed.length ? attributedRows(attribution?.plugins) : pluginRows,
      hue: "--chr-peak",
      sub: attributed.length
        ? "Turns and tokens spent under each plugin — what it cost, not how often it ran. "
          + "Built-in skills carry no plugin and are excluded."
        : "Plugin-provided MCP servers and plugin skills. A plugin's MCP calls are counted on the MCP tab too.",
      empty: "No plugin usage recorded. Historical sessions need a `chronicle sync --full` to backfill.",
    },
    {
      // Skills are stamped on the turn like plugins, and a built-in skill
      // carries no plugin at all — so it is only ever visible here. The
      // plugin it came from rides along in the detail line.
      key: "skills",
      label: "Skills",
      count: attribution?.skills.length ?? 0,
      rows: attributedRows(attribution?.skills),
      hue: "--chr-output",
      sub: "Turns and tokens spent under each skill, built-in ones included.",
      empty: "No skill usage recorded. Historical sessions need a `chronicle sync --full` to backfill.",
    },
    {
      key: "agents",
      label: "Agents",
      count: attribution?.agents.length ?? 0,
      rows: attributedRows(attribution?.agents),
      hue: "--chr-turns",
      sub: attribution
        ? `Turns and tokens spent inside subagents, by type. ${formatTokens(attribution.attributed_turns)} `
          + `of ${formatTokens(attribution.turns)} turns had anything in scope — most have nothing, correctly.`
        : "Turns and tokens spent inside subagents, by type.",
      empty: "No subagent attribution recorded. Historical sessions need a `chronicle sync --full` to backfill.",
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
              {v.label}{" "}
              <span className="chr-usage__count">
                {v.countLabel ?? formatTokens(v.count)}
              </span>
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
            format={active.format ?? formatTokens}
            title={`${active.label} breakdown`}
            hue={active.hue}
          />
        </div>
      )}
    </section>
  );
}
