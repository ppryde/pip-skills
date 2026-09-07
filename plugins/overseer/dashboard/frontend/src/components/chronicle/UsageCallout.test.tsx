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

const CHURN = {
  lines_added: 5951, lines_removed: 2542, files: 2, edits: 472,
  sessions: 9, output_tokens: 1_000_000, by_day: [],
  files_by_churn: [
    { file_path: "/repos/pip-skills/src/styles.css", edits: 472,
      lines_added: 5951, lines_removed: 2542, operations: ["edit"], sessions: 9 },
    { file_path: "/repos/pip-skills/src/New.tsx", edits: 1,
      lines_added: 40, lines_removed: 0, operations: ["create"], sessions: 1 },
  ],
};

const ATTRIBUTION = {
  turns: 100, attributed_turns: 12, cost_usd: 683.0, unattributed_cost_usd: 14095.0,
  plugins: [
    { name: "superpowers", turns: 2987, context_tokens: 427_400_000,
      output_tokens: 1_694_000, sessions: 31, cost_usd: 292.52, skills: 9 },
  ],
  skills: [
    { name: "code-review", turns: 9, context_tokens: 1000, output_tokens: 50,
      sessions: 4, cost_usd: 1.2, plugin: null },
  ],
  agents: [
    { name: "general-purpose", turns: 10619, context_tokens: 1_032_000_000,
      output_tokens: 847_000, sessions: 60, cost_usd: 390.35 },
  ],
  mcp: [],
};

describe("<UsageCallout/>", () => {
  it("prefers attribution on the Plugins tab — cost, not invocation count", () => {
    const { container } = render(
      <UsageCallout tools={TOOLS} plugins={PLUGINS} attribution={ATTRIBUTION} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    expect(screen.getByText("superpowers")).toBeInTheDocument();
    const row = container.querySelector(".chr-barlist__row") as HTMLElement;
    expect(row.title).toContain("2987 turns");
    // formatUsd rounds above $100 — the shared formatter's call, not ours.
    expect(row.title).toContain("$293");
    // The old call-count row is NOT what is shown when attribution exists.
    expect(screen.queryByText("playwright · mcp")).not.toBeInTheDocument();
  });

  it("falls back to call counts when the store has no attribution yet", () => {
    render(<UsageCallout tools={TOOLS} plugins={PLUGINS} />);
    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    expect(screen.getByText("playwright · mcp")).toBeInTheDocument();
  });

  it("accounts for subagents by type, and says how many turns were attributed", () => {
    render(<UsageCallout tools={TOOLS} attribution={ATTRIBUTION} />);
    fireEvent.click(screen.getByRole("button", { name: /^Agents/ }));
    expect(screen.getByText("general-purpose")).toBeInTheDocument();
    // The denominator is stated: most turns have nothing in scope, and a
    // reader must not take 12 attributed turns for the whole picture.
    expect(screen.getByText(/12 of 100 turns had anything in scope/)).toBeInTheDocument();
  });

  it("ranks files by how much moved, and keeps the full path in the detail", () => {
    const { container } = render(<UsageCallout tools={TOOLS} churn={CHURN} />);
    fireEvent.click(screen.getByRole("button", { name: /^Files/ }));
    // Label is trimmed to the last two segments so a deep path stays legible;
    // the full path lives in the hover detail rather than being lost.
    expect(screen.getByText("src/styles.css")).toBeInTheDocument();
    const row = container.querySelector(".chr-barlist__row") as HTMLElement;
    expect(row.title).toContain("/repos/pip-skills/src/styles.css");
    expect(row.title).toContain("472 edits");
    expect(row.title).toContain("+5951 / -2542");
  });

  it("marks a file the session created rather than edited", () => {
    const { container } = render(<UsageCallout tools={TOOLS} churn={CHURN} />);
    fireEvent.click(screen.getByRole("button", { name: /^Files/ }));
    const rows = container.querySelectorAll(".chr-barlist__row");
    expect((rows[1] as HTMLElement).title).toContain("created here");
    expect((rows[0] as HTMLElement).title).not.toContain("created here");
  });

  it("says churn is editing done, not what shipped", () => {
    render(<UsageCallout tools={TOOLS} churn={CHURN} />);
    fireEvent.click(screen.getByRole("button", { name: /^Files/ }));
    // The measure is easy to misread as "lines of code written", so the
    // caveat sits on the tab itself rather than in a doc nobody opens.
    expect(screen.getByText(/git is the source for what shipped/)).toBeInTheDocument();
  });

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
