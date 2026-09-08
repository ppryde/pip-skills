import { useMemo, useState } from "react";

import { formatBytes, formatDuration, formatTokens } from "../../board/chronicle/format";
import { groupMcpTools } from "../../board/chronicle/mcp";
import type { ChronicleMcp, ChronicleMcpTool } from "../../api/types";
import { Select } from "../../ui";

interface McpExplorerProps {
  mcp?: ChronicleMcp;
  /** Per-session copy drops the sessions column, which would read "1" on
   * every row in a drawer. */
  perSession?: boolean;
}

/**
 * The MCP breakdown at TOOL grain — which of a server's tools were actually
 * called, and what each of them cost.
 *
 * The usage callout's MCP tab ranks SERVERS, which answers "how much Notion"
 * but never "Notion doing what": one bar hides seventeen playwright tools,
 * and a server whose calls are one cheap `search` reads identically to one
 * whose calls are seventeen expensive `fetch`es. The backend has carried the
 * per-tool rows since the block was written (`_ranked("mcptool")`) — nothing
 * had ever rendered them.
 *
 * A table rather than the callout's bar list because every column here is a
 * DIFFERENT measure — calls, bytes back, wall time, delegation — and a bar
 * list can only rank one. The server picker narrows it, defaulting to the
 * busiest server rather than to everything: "all servers" ranks Notion's
 * `fetch` above Linear's `list_issues` and answers no question anyone asks
 * of this table. It stays available as an option for cross-server comparison.
 */
export default function McpExplorer({ mcp, perSession }: McpExplorerProps) {
  const groups = useMemo(() => groupMcpTools(mcp), [mcp]);
  // The busiest server, which `groupMcpTools` already sorted to the front.
  // Held as a slug rather than an index so it survives a window change that
  // reorders the list; an unknown slug falls back below rather than blanking.
  const [server, setServer] = useState<string>("");

  if (groups.length === 0) {
    return (
      <section className="chr-panel chr-panel--wide" style={{ ["--chr-hue" as string]: "var(--chr-context)" }}>
        <h3 className="chr-panel__title">MCP tools</h3>
        <p className="chr-chart__empty">No MCP calls in this window.</p>
      </section>
    );
  }

  const selected = groups.find((g) => g.server === server);
  const active = server === "all" ? null : selected ?? groups[0];

  const rows: (ChronicleMcpTool & { serverName: string })[] = (active ? [active] : groups)
    .flatMap((g) => g.tools.map((t) => ({ ...t, serverName: g.name })));
  // Re-rank only when the selection merged several servers; a single group is
  // already in call order from `groupMcpTools`.
  if (!active) rows.sort((a, b) => b.calls - a.calls || a.tool.localeCompare(b.tool));

  const sub = active
    ? [
        active.provenance,
        `${active.tools.length} ${active.tools.length === 1 ? "tool" : "tools"} called`,
        `${formatTokens(active.calls)} calls`,
        active.result_chars ? `${formatBytes(active.result_chars)} returned` : null,
        active.name !== active.server ? active.server : null,
      ].filter(Boolean).join(" · ")
    : `Every MCP tool across ${groups.length} ${groups.length === 1 ? "server" : "servers"}, `
      + `most-called first.`;

  return (
    <section className="chr-panel chr-panel--wide" style={{ ["--chr-hue" as string]: "var(--chr-context)" }}>
      <div className="chr-panel__head">
        <h3 className="chr-panel__title">MCP tools</h3>
        {/* The caption is laid out here rather than through `Select`'s own
            `label` prop, which stacks it above the control — this one has to
            sit inline beside the panel title. */}
        <label className="chr-mcp__pick">
          <span className="qb-label">Server</span>
          <Select
            className="chr-mcp__picker"
            value={active ? active.server : "all"}
            onChange={(e) => setServer(e.target.value)}
          >
            {groups.map((g) => (
              <option key={g.server} value={g.server}>
                {g.name} ({g.calls})
              </option>
            ))}
            <option value="all">All servers</option>
          </Select>
        </label>
      </div>
      <p className="chr-panel__sub">{sub}</p>
      {rows.length === 0 ? (
        // A server can rank in the servers list while none of its tools make
        // the separate per-tool cap. Say which server is empty and why, rather
        // than showing a bare "no data" under a picker that clearly has one.
        <p className="chr-chart__empty">
          No per-tool rows for {active?.name ?? "this server"} — its calls fell outside the
          per-tool ranking. A `chronicle sync --full` refreshes the store.
        </p>
      ) : (
        <div className="chr-usage__scroll">
          <table className="chr-table chr-table--compact chr-mcp__table" aria-label="MCP tools">
            <thead>
              <tr>
                <th scope="col">Tool</th>
                {!active && <th scope="col">Server</th>}
                <th scope="col">Calls</th>
                <th scope="col">Returned</th>
                <th scope="col">Typical</th>
                <th scope="col">Delegated</th>
                {!perSession && <th scope="col">Sessions</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={`${t.server}/${t.tool}`}>
                  <td className="chr-mono">{t.tool}</td>
                  {!active && <td>{t.serverName}</td>}
                  <td className="chr-num">{t.calls.toLocaleString()}</td>
                  {/* An em dash, not "0 B": a tool whose results never came
                      back is a different claim from one that returned nothing. */}
                  <td className="chr-num">{t.result_chars ? formatBytes(t.result_chars) : "—"}</td>
                  <td className="chr-num">{t.median_s != null ? formatDuration(t.median_s) : "—"}</td>
                  <td className="chr-num">
                    {t.subagent_calls ? `${Math.round((t.subagent_calls / t.calls) * 100)}%` : "—"}
                  </td>
                  {!perSession && <td className="chr-num">{t.sessions ?? "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
