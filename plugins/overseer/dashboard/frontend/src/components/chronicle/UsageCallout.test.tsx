import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsageCallout from "./UsageCallout";

const TOOLS = [{ tool_name: "Bash", calls: 60, sessions: 2, result_chars: 1200, median_s: 2.5, subagent_calls: 30 }];
const MCP = {
  calls: 4,
  result_chars: 900,
  by_provenance: { plugin: 2, connector: 1, local: 1 },
  servers: [
    { server: "claude_ai_Notion", provenance: "connector", tools: 6, calls: 3, result_chars: 500, median_s: 1.5, subagent_calls: 0 },
    { server: "claude-in-chrome", provenance: "local", tools: 1, calls: 1, result_chars: 400, median_s: 1.5, subagent_calls: 0 },
  ],
  tools: [],
  sessions: 1,
};
const PLUGINS = {
  calls: 3,
  sessions: 1,
  items: [
    { plugin: "playwright", kind: "mcp", calls: 2, sessions: 1, result_chars: 0, median_s: null, subagent_calls: 0 },
    { plugin: "tribunal", kind: "skill", calls: 1, sessions: 1, result_chars: 0, median_s: null, subagent_calls: 0 },
  ],
};

describe("<UsageCallout/>", () => {
  it("shows tool calls first, with MCP and plugins a click away", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    const group = screen.getByRole("group", { name: "Usage breakdown" });
    expect(within(group).getByRole("button", { name: /^Tools/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Bash")).toBeInTheDocument();
    expect(screen.queryByText("claude_ai_Notion")).not.toBeInTheDocument();
  });

  it("switches to the MCP breakdown, showing server names in full", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    // The whole point of the consolidation: a full-width row has the space
    // for `claude_ai_Notion` rather than clipping it to `claude_ai_N…`.
    expect(screen.getByText("claude_ai_Notion")).toBeInTheDocument();
    expect(screen.getByText("claude-in-chrome")).toBeInTheDocument();
    expect(screen.queryByText("Bash")).not.toBeInTheDocument();
  });

  it("switches to the plugin breakdown", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    expect(screen.getByText("playwright · mcp")).toBeInTheDocument();
    expect(screen.getByText("tribunal · skill")).toBeInTheDocument();
  });

  it("counts each breakdown on its own tab", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    expect(screen.getByRole("button", { name: "Tools 60" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MCP 4" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plugins 3" })).toBeInTheDocument();
  });

  it("explains an empty plugin breakdown rather than showing a bare zero", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={{ calls: 0, items: [] }} />);
    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    expect(screen.getByText(/chronicle sync --full/)).toBeInTheDocument();
  });

  it("reports what a tool cost, not just how often it ran", () => {
    const { container } = render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    const row = container.querySelector(".chr-barlist__row") as HTMLElement;
    // Volume, wall time and delegated share all come off columns the store
    // already had and nothing reported.
    expect(row.title).toContain("60 calls");
    expect(row.title).toContain("returned");
    expect(row.title).toContain("typical");
    expect(row.title).toContain("50% delegated");
  });

  it("omits a measure it does not have rather than claiming zero", () => {
    // median_s is null for these plugin rows: no call landed both timestamps.
    // "0s typical" would be a different claim from "we don't know".
    const { container } = render(<UsageCallout tools={TOOLS} plugins={PLUGINS} />);
    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    const row = container.querySelector(".chr-barlist__row") as HTMLElement;
    expect(row.title).toContain("2 calls");
    expect(row.title).not.toContain("typical");
    expect(row.title).not.toContain("delegated");
  });

  it("scrolls a long list instead of truncating its tail", () => {
    const many = Array.from({ length: 40 }, (_, i) => ({
      tool_name: `Tool${i}`, calls: 40 - i, sessions: 1,
      result_chars: 10, median_s: 1, subagent_calls: 0,
    }));
    const { container } = render(<UsageCallout tools={many} />);
    // Every row is rendered — the container scrolls, nothing is cut.
    expect(container.querySelectorAll(".chr-barlist__row")).toHaveLength(40);
    expect(container.querySelector(".chr-usage__scroll")).not.toBeNull();
    expect(screen.getByText("Tool39")).toBeInTheDocument();
  });

  it("survives a payload from a backend that predates the blocks", () => {
    render(<UsageCallout tools={TOOLS} />);
    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    expect(screen.getByText(/No MCP calls/)).toBeInTheDocument();
  });
});
