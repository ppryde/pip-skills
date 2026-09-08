import { describe, expect, it } from "vitest";

import { groupMcpTools, mcpServerNames, mcpToolLabel, parseMcpToolName } from "./mcp";
import type { ChronicleMcp } from "../../api/types";

const usage = { result_chars: 0, median_s: null, subagent_calls: 0 };

const MCP: ChronicleMcp = {
  calls: 130,
  result_chars: 4000,
  by_provenance: { connector: 100, plugin: 30 },
  servers: [
    { server: "claude_ai_Notion", name: "claude.ai Notion", provenance: "connector",
      tools: 2, calls: 100, result_chars: 3000, median_s: 1.5, subagent_calls: 10 },
    { server: "plugin_linear_linear", provenance: "plugin",
      tools: 1, calls: 30, result_chars: 1000, median_s: null, subagent_calls: 0 },
  ],
  tools: [
    { server: "claude_ai_Notion", name: "claude.ai Notion", tool: "fetch", calls: 84, ...usage },
    { server: "claude_ai_Notion", name: "claude.ai Notion", tool: "search", calls: 16, ...usage },
    { server: "plugin_linear_linear", tool: "list_issues", calls: 30, ...usage },
  ],
};

describe("parseMcpToolName", () => {
  it("splits a server slug from its tool", () => {
    expect(parseMcpToolName("mcp__claude_ai_Notion__fetch"))
      .toEqual({ server: "claude_ai_Notion", tool: "fetch" });
  });

  it("keeps a double underscore that belongs to the tool's own name", () => {
    // Partitions on the FIRST separator, exactly as `classify()` does.
    expect(parseMcpToolName("mcp__srv__slack__send_message"))
      .toEqual({ server: "srv", tool: "slack__send_message" });
  });

  it("returns null for a built-in tool", () => {
    expect(parseMcpToolName("Bash")).toBeNull();
  });

  it("refuses to guess at a malformed name rather than inventing a server", () => {
    expect(parseMcpToolName("mcp__onlyserver")).toBeNull();
    expect(parseMcpToolName("mcp____tool")).toBeNull();
    expect(parseMcpToolName("mcp__server__")).toBeNull();
  });
});

describe("mcpServerNames", () => {
  it("prefers the name the servers block records", () => {
    expect(mcpServerNames(MCP).get("claude_ai_Notion")).toBe("claude.ai Notion");
  });

  it("enters nothing for a server attribution never named", () => {
    expect(mcpServerNames(MCP).has("plugin_linear_linear")).toBe(false);
  });

  it("falls back to the tools block when only it carries the name", () => {
    const names = mcpServerNames({ ...MCP, servers: [] });
    expect(names.get("claude_ai_Notion")).toBe("claude.ai Notion");
  });

  it("survives a payload with no MCP block at all", () => {
    expect(mcpServerNames(undefined).size).toBe(0);
  });
});

describe("mcpToolLabel", () => {
  const names = mcpServerNames(MCP);

  it("names the server as attribution records it", () => {
    expect(mcpToolLabel("mcp__claude_ai_Notion__fetch", names)).toBe("claude.ai Notion · fetch");
  });

  it("falls back to the slug where no name was recorded", () => {
    expect(mcpToolLabel("mcp__plugin_linear_linear__list_issues", names))
      .toBe("plugin_linear_linear · list_issues");
  });

  it("passes a built-in tool through untouched", () => {
    expect(mcpToolLabel("Bash", names)).toBe("Bash");
  });
});

describe("groupMcpTools", () => {
  it("hangs each server's tools under it, busiest server first", () => {
    const groups = groupMcpTools(MCP);
    expect(groups.map((g) => g.name))
      .toEqual(["claude.ai Notion", "plugin_linear_linear"]);
    expect(groups[0].tools.map((t) => t.tool)).toEqual(["fetch", "search"]);
    expect(groups[0].provenance).toBe("connector");
  });

  it("keeps a tool whose server never made the capped servers list", () => {
    // Both lists are capped server-side, so this is a real payload shape —
    // and a call without its server is still a call.
    const groups = groupMcpTools({ ...MCP, servers: [MCP.servers[0]] });
    const orphan = groups.find((g) => g.server === "plugin_linear_linear");
    expect(orphan?.calls).toBe(30);
    // Provenance is a property of the server block, which is what is missing.
    expect(orphan?.provenance).toBeNull();
  });

  it("gives a server with no per-tool rows an empty group rather than dropping it", () => {
    const groups = groupMcpTools({ ...MCP, tools: [] });
    expect(groups).toHaveLength(2);
    expect(groups[0].tools).toEqual([]);
  });

  it("returns nothing for a window with no MCP calls", () => {
    expect(groupMcpTools(undefined)).toEqual([]);
  });
});
