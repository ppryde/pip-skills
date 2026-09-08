/**
 * Reading an MCP call's identity out of a tool name, and grouping the
 * per-tool breakdown by the server it came from.
 *
 * Claude Code writes an MCP call as `mcp__<server-slug>__<tool>`, where the
 * slug is the server's real name with every character outside `[A-Za-z0-9-]`
 * replaced by an underscore. So the raw name carries the slug and nothing
 * better: `mcp__claude_ai_Notion__fetch`. Attribution stamps the server's
 * ACTUAL name onto the turn, and the backend joins the two — which is why
 * `ChronicleMcpServer.name` and `ChronicleMcpTool.name` exist.
 *
 * The parse mirrors `classify()` in `plugins/chronicle/scripts/report.py`
 * exactly, including its refusal to guess: a name that splits into an empty
 * half is not an MCP call as far as this module is concerned, and the caller
 * keeps the raw string rather than inventing a server for it.
 */
import type { ChronicleMcp, ChronicleMcpTool } from "../../api/types";

const MCP_PREFIX = "mcp__";

export interface McpRef {
  /** The slug the tool name spells the server with (`claude_ai_Notion`). */
  server: string;
  /** Everything after the second separator — `fetch`, `create-pages`. */
  tool: string;
}

/** `mcp__claude_ai_Notion__fetch` -> `{ server, tool }`; null for anything
 * that is not an MCP tool name, and for a malformed one. Partitions on the
 * FIRST `__` after the prefix, so a tool whose own name contains `__` keeps
 * it. */
export function parseMcpToolName(toolName: string): McpRef | null {
  if (!toolName.startsWith(MCP_PREFIX)) return null;
  const rest = toolName.slice(MCP_PREFIX.length);
  const at = rest.indexOf("__");
  if (at <= 0) return null;
  const server = rest.slice(0, at);
  const tool = rest.slice(at + 2);
  return server && tool ? { server, tool } : null;
}

/**
 * Slug -> the server's real name, built from whichever blocks the payload
 * carries. Servers and tools both record it, and a store predating the join
 * records neither — an absent name is simply not entered, so a lookup misses
 * and the caller falls back to the slug rather than to `undefined`.
 */
export function mcpServerNames(mcp: ChronicleMcp | undefined): Map<string, string> {
  const names = new Map<string, string>();
  for (const s of mcp?.servers ?? []) if (s.name) names.set(s.server, s.name);
  for (const t of mcp?.tools ?? []) if (t.name && !names.has(t.server)) names.set(t.server, t.name);
  return names;
}

/**
 * A tool call's label for a mixed list: `claude.ai Notion · fetch` for an MCP
 * call, and the raw name unchanged for everything else.
 *
 * The Tools tab ranks EVERY call, MCP and built-in together, and left raw it
 * showed `mcp__claude_ai_Notion__fetch` beside `Bash` — the one list where
 * the slug was still on display after the MCP tab learned the real name.
 * Callers keep the raw name in the row's detail, so nothing that might be
 * searched for is lost.
 */
export function mcpToolLabel(toolName: string, names: Map<string, string>): string {
  const ref = parseMcpToolName(toolName);
  if (!ref) return toolName;
  return `${names.get(ref.server) ?? ref.server} · ${ref.tool}`;
}

export interface McpServerGroup {
  /** The slug — the key everything joins on, and the label of last resort. */
  server: string;
  /** The real name where attribution recorded one, else the slug. */
  name: string;
  /** "plugin" | "connector" | "local", or null for a server known only from
   * its tools (see below), where the payload never states it. */
  provenance: string | null;
  calls: number;
  result_chars: number;
  tools: ChronicleMcpTool[];
}

/**
 * The per-tool list, grouped under its server and ranked by calls.
 *
 * Driven by `mcp.servers` so the order matches the MCP tab's, then swept for
 * tools whose server never made that list — both lists are capped
 * server-side, and a tool without its server is still a real call. Such a
 * group's totals are summed from the tools alone, which is why `provenance`
 * is null there: it is a property of the server, and this payload does not
 * carry it.
 */
export function groupMcpTools(mcp: ChronicleMcp | undefined): McpServerGroup[] {
  const names = mcpServerNames(mcp);
  const byServer = new Map<string, ChronicleMcpTool[]>();
  for (const t of mcp?.tools ?? []) {
    const list = byServer.get(t.server);
    if (list) list.push(t);
    else byServer.set(t.server, [t]);
  }

  const groups: McpServerGroup[] = (mcp?.servers ?? []).map((s) => ({
    server: s.server,
    name: s.name ?? names.get(s.server) ?? s.server,
    provenance: s.provenance,
    calls: s.calls,
    result_chars: s.result_chars,
    tools: byServer.get(s.server) ?? [],
  }));

  const known = new Set(groups.map((g) => g.server));
  for (const [server, tools] of byServer) {
    if (known.has(server)) continue;
    groups.push({
      server,
      name: names.get(server) ?? server,
      provenance: null,
      calls: tools.reduce((n, t) => n + t.calls, 0),
      result_chars: tools.reduce((n, t) => n + t.result_chars, 0),
      tools,
    });
  }

  // Calls descending, then name ascending so equal counts hold still between
  // renders — the same tiebreak the backend's `_ranked` uses.
  groups.sort((a, b) => b.calls - a.calls || a.name.localeCompare(b.name));
  for (const g of groups) {
    g.tools.sort((a, b) => b.calls - a.calls || a.tool.localeCompare(b.tool));
  }
  return groups;
}
