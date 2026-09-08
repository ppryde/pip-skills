import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import McpExplorer from "./McpExplorer";
import type { ChronicleMcp } from "../../api/types";

const MCP: ChronicleMcp = {
  calls: 130,
  result_chars: 4000,
  by_provenance: { connector: 100, plugin: 30 },
  servers: [
    { server: "claude_ai_Notion", name: "claude.ai Notion", provenance: "connector",
      tools: 2, calls: 100, result_chars: 3000, median_s: 1.5, subagent_calls: 10, sessions: 4 },
    { server: "plugin_linear_linear", provenance: "plugin",
      tools: 1, calls: 30, result_chars: 1000, median_s: null, subagent_calls: 0, sessions: 2 },
  ],
  tools: [
    { server: "claude_ai_Notion", name: "claude.ai Notion", tool: "fetch",
      calls: 84, result_chars: 2800, median_s: 2.5, subagent_calls: 42, sessions: 4 },
    { server: "claude_ai_Notion", name: "claude.ai Notion", tool: "search",
      calls: 16, result_chars: 200, median_s: null, subagent_calls: 0, sessions: 2 },
    { server: "plugin_linear_linear", tool: "list_issues",
      calls: 30, result_chars: 1000, median_s: 0.4, subagent_calls: 0, sessions: 2 },
  ],
};

const bodyRows = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("tbody tr"));

describe("<McpExplorer/>", () => {
  it("opens on the busiest server, showing its tools rather than every server's", () => {
    const { container } = render(<McpExplorer mcp={MCP} />);
    const rows = bodyRows(container);
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText("fetch")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("search")).toBeInTheDocument();
    expect(screen.queryByText("list_issues")).not.toBeInTheDocument();
  });

  it("carries the four measures a bar list cannot rank at once", () => {
    const { container } = render(<McpExplorer mcp={MCP} />);
    const row = bodyRows(container)[0] as HTMLElement;
    expect(within(row).getByText("84")).toBeInTheDocument();          // calls
    expect(within(row).getByText("2.7 KB")).toBeInTheDocument();      // returned
    expect(within(row).getByText("3s")).toBeInTheDocument();          // typical
    expect(within(row).getByText("50%")).toBeInTheDocument();         // delegated
  });

  it("says the server's real name and provenance, keeping the slug alongside", () => {
    render(<McpExplorer mcp={MCP} />);
    const sub = screen.getByText(/connector/);
    expect(sub).toHaveTextContent("2 tools called");
    expect(sub).toHaveTextContent("claude_ai_Notion");
  });

  it("switches the table to another server", () => {
    const { container } = render(<McpExplorer mcp={MCP} />);
    fireEvent.change(screen.getByLabelText("Server"), { target: { value: "plugin_linear_linear" } });
    const rows = bodyRows(container);
    expect(rows).toHaveLength(1);
    expect(within(rows[0] as HTMLElement).getByText("list_issues")).toBeInTheDocument();
  });

  it("adds a server column only when the selection spans several servers", () => {
    const { container } = render(<McpExplorer mcp={MCP} />);
    expect(screen.queryByRole("columnheader", { name: "Server" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Server"), { target: { value: "all" } });
    expect(screen.getByRole("columnheader", { name: "Server" })).toBeInTheDocument();
    expect(bodyRows(container)).toHaveLength(3);
  });

  it("distinguishes an unknown measure from a zero one", () => {
    const { container } = render(<McpExplorer mcp={MCP} />);
    // `search` has no median — an em dash, never "0s", which would claim the
    // calls returned instantly.
    const row = bodyRows(container)[1] as HTMLElement;
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("drops the sessions column in a per-session view", () => {
    render(<McpExplorer mcp={MCP} perSession />);
    expect(screen.queryByRole("columnheader", { name: "Sessions" })).not.toBeInTheDocument();
  });

  it("says so plainly when the window has no MCP calls", () => {
    render(<McpExplorer />);
    expect(screen.getByText("No MCP calls in this window.")).toBeInTheDocument();
  });

  it("names the empty server when it ranked but none of its tools did", () => {
    render(<McpExplorer mcp={{ ...MCP, tools: [] }} />);
    expect(screen.getByText(/No per-tool rows for claude\.ai Notion/)).toBeInTheDocument();
  });
});
