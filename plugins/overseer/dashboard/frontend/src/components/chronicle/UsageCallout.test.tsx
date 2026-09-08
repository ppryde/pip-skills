import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsageCallout from "./UsageCallout";

const TOOLS = [
  { tool_name: "Bash", calls: 60, sessions: 2, result_chars: 1200, median_s: 2.5, subagent_calls: 30 },
  { tool_name: "mcp__claude_ai_Notion__fetch", calls: 3, sessions: 1, result_chars: 500, median_s: 1.5, subagent_calls: 0 },
  { tool_name: "mcp__claude-in-chrome__navigate", calls: 1, sessions: 1, result_chars: 400, median_s: null, subagent_calls: 0 },
];
const MCP = {
  calls: 4,
  result_chars: 900,
  by_provenance: { plugin: 2, connector: 1, local: 1 },
  servers: [
    { server: "claude_ai_Notion", name: "claude.ai Notion", provenance: "connector", tools: 6, calls: 3, result_chars: 500, median_s: 1.5, subagent_calls: 0 },
    { server: "claude-in-chrome", name: "claude-in-chrome", provenance: "local", tools: 1, calls: 1, result_chars: 400, median_s: 1.5, subagent_calls: 0 },
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
    // Same last two segments as the first row, a different file. The real
    // store has three of these; labels are not unique, paths are.
    { file_path: "/repos/other/src/styles.css", edits: 3,
      lines_added: 12, lines_removed: 4, operations: ["edit"], sessions: 1 },
  ],
};

const CONTEXT_GROWTH = {
  // Mirrors the real store's shape: the second tool is called twenty times
  // more often and still returns less than a third as much.
  result_chars: 3_200_000,
  calls: 1205,
  measured_calls: 1200,
  tools_total: 27,
  tools: [
    { tool_name: "Read", calls: 200, measured_calls: 200,
      result_chars: 2_200_000, share: 0.6875, avg_chars: 11_000 },
    { tool_name: "Bash", calls: 1000, measured_calls: 995,
      result_chars: 995_000, share: 0.3109, avg_chars: 1000 },
    { tool_name: "Edit", calls: 5, measured_calls: 5,
      result_chars: 5000, share: 0.0016, avg_chars: 1000 },
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

describe("<UsageCallout/> Tools tab", () => {
  // The Tools tab ranks EVERY call, so it was the one list still showing an
  // MCP call by its raw slug after the MCP tab had learnt the real name.
  it("names an MCP call by its server's attributed name, not its slug", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} />);
    expect(screen.getByText("claude.ai Notion · fetch")).toBeInTheDocument();
    expect(screen.queryByText("mcp__claude_ai_Notion__fetch")).not.toBeInTheDocument();
  });

  it("keeps the raw name in the row's detail, where it can still be found", () => {
    const { container } = render(<UsageCallout tools={TOOLS} mcp={MCP} />);
    const row = Array.from(container.querySelectorAll(".chr-barlist__row"))
      .find((r) => r.textContent?.includes("claude.ai Notion · fetch")) as HTMLElement;
    expect(row.title).toContain("mcp__claude_ai_Notion__fetch");
  });

  it("leaves a built-in tool's name alone, detail and all", () => {
    const { container } = render(<UsageCallout tools={TOOLS} mcp={MCP} />);
    expect(screen.getByText("Bash")).toBeInTheDocument();
    const row = Array.from(container.querySelectorAll(".chr-barlist__row"))
      .find((r) => r.textContent?.includes("Bash")) as HTMLElement;
    expect(row.title).not.toContain("mcp__");
  });

  it("falls back to the slug for a server attribution never named", () => {
    render(<UsageCallout tools={TOOLS} mcp={{ ...MCP, servers: [] }} />);
    expect(screen.getByText("claude_ai_Notion · fetch")).toBeInTheDocument();
  });
});

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
    // the full path lives in the hover detail rather than being lost. Two
    // different files share this label, which is exactly why the row is keyed
    // by path.
    expect(screen.getAllByText("src/styles.css")).toHaveLength(2);
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
    const { container } = render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    // The whole point of the consolidation: a full-width row has the space
    // for the whole name rather than clipping it to `claude_ai_N…`. And the
    // name shown is the one attribution recorded — `claude.ai Notion`, not
    // the slug the tool name spells it with.
    expect(screen.getByText("claude.ai Notion")).toBeInTheDocument();
    expect(screen.getByText("claude-in-chrome")).toBeInTheDocument();
    expect(screen.queryByText("Bash")).not.toBeInTheDocument();
    // The slug is still there to search for, in the detail line.
    const row = container.querySelector(".chr-barlist__row") as HTMLElement;
    expect(row.title).toContain("claude_ai_Notion");
  });

  it("falls back to the slug for a server attribution never named", () => {
    render(<UsageCallout tools={TOOLS} mcp={{
      ...MCP,
      servers: [{ server: "claude_ai_Wayflyer_Staff", provenance: "connector", tools: 1,
                  calls: 1, result_chars: 0, median_s: null, subagent_calls: 0 }],
    }} />);
    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    expect(screen.getByText("claude_ai_Wayflyer_Staff")).toBeInTheDocument();
  });

  it("does not repeat the slug when it is already the name", () => {
    const { container } = render(<UsageCallout tools={TOOLS} mcp={MCP} />);
    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    const rows = container.querySelectorAll(".chr-barlist__row");
    // "claude-in-chrome" needs no slugging, so its detail says it once.
    const chrome = [...rows].find((r) => r.textContent?.includes("claude-in-chrome")) as HTMLElement;
    expect(chrome.title.match(/claude-in-chrome/g)).toBeNull();
  });

  it("switches to the plugin breakdown", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    expect(screen.getByText("playwright · mcp")).toBeInTheDocument();
    expect(screen.getByText("tribunal · skill")).toBeInTheDocument();
  });

  it("counts each breakdown on its own tab", () => {
    render(<UsageCallout tools={TOOLS} mcp={MCP} plugins={PLUGINS} />);
    expect(screen.getByRole("button", { name: "Tools 64" })).toBeInTheDocument();
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

  it("leaves nothing of the file list behind when the tab changes", () => {
    // Two of the churn rows shorten to the same label. Keyed by label, React
    // could not tell them apart and left one stranded in the DOM when the
    // list was replaced — so switching off Files showed file rows among the
    // tools. Keyed by path, the swap is clean.
    const { container } = render(<UsageCallout tools={TOOLS} churn={CHURN} />);
    fireEvent.click(screen.getByRole("button", { name: /^Files/ }));
    expect(container.querySelectorAll(".chr-barlist__row")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: /^Tools/ }));
    expect(container.querySelectorAll(".chr-barlist__row")).toHaveLength(TOOLS.length);
    expect(screen.queryByText("src/styles.css")).not.toBeInTheDocument();
    expect(screen.queryByText("src/New.tsx")).not.toBeInTheDocument();
    expect(screen.getByText("Bash")).toBeInTheDocument();
  });

  it("keeps both files that shorten to the same label", () => {
    const { container } = render(<UsageCallout tools={TOOLS} churn={CHURN} />);
    fireEvent.click(screen.getByRole("button", { name: /^Files/ }));
    const titles = [...container.querySelectorAll(".chr-barlist__row")]
      .map((r) => (r as HTMLElement).title);
    expect(titles.some((t) => t.startsWith("/repos/pip-skills/src/styles.css"))).toBe(true);
    expect(titles.some((t) => t.startsWith("/repos/other/src/styles.css"))).toBe(true);
  });

  it("breaks skills out on their own tab, built-ins included", () => {
    // A built-in skill carries no plugin at all, so the Plugins tab can never
    // show it — this tab is the only place it appears.
    render(<UsageCallout tools={TOOLS} attribution={ATTRIBUTION} />);
    fireEvent.click(screen.getByRole("button", { name: /^Skills/ }));
    expect(screen.getByText("code-review")).toBeInTheDocument();
  });

  it("survives a payload from a backend that predates the blocks", () => {
    render(<UsageCallout tools={TOOLS} />);
    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    expect(screen.getByText(/No MCP calls/)).toBeInTheDocument();
  });
});

describe("<UsageCallout/> Context tab", () => {
  it("ranks by what a tool returned, not by how often it ran", () => {
    // The finding the tab exists for: Bash out-calls Read five to one and is
    // still second, because the average Read is eleven times the size.
    const { container } = render(
      <UsageCallout tools={TOOLS} contextGrowth={CONTEXT_GROWTH} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    const labels = [...container.querySelectorAll(".chr-barlist__label")]
      .map((n) => n.textContent);
    expect(labels).toEqual(["Read", "Bash", "Edit"]);
  });

  it("states a share of what was returned, and the typical size behind it", () => {
    const { container } = render(
      <UsageCallout tools={TOOLS} contextGrowth={CONTEXT_GROWTH} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    const read = container.querySelector(".chr-barlist__row") as HTMLElement;
    expect(read.title).toContain("69% of everything returned");
    expect(read.title).toContain("200 calls");
    expect(read.title).toContain("10.7 KB per call");
  });

  it("never rounds a small share down to nothing", () => {
    // Edit is 0.16% of the window — 5 KB, not zero. "0%" would be a lie the
    // reader could not catch.
    const { container } = render(
      <UsageCallout tools={TOOLS} contextGrowth={CONTEXT_GROWTH} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    const edit = [...container.querySelectorAll(".chr-barlist__row")]
      .find((r) => r.textContent?.includes("Edit")) as HTMLElement;
    expect(edit.title).toContain("0.2% of everything returned");
    expect(edit.title).not.toContain("0% of");
  });

  it("says how many calls went unmeasured rather than averaging over them", () => {
    const { container } = render(
      <UsageCallout tools={TOOLS} contextGrowth={CONTEXT_GROWTH} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    const bash = [...container.querySelectorAll(".chr-barlist__row")]
      .find((r) => r.textContent?.includes("Bash")) as HTMLElement;
    // 1000 calls, 995 sizes recorded — the average divides by 995.
    expect(bash.title).toContain("5 unmeasured");
    expect(bash.title).toContain("1000 B per call");
  });

  it("counts the tab in bytes, since the measure is characters not tokens", () => {
    render(<UsageCallout tools={TOOLS} contextGrowth={CONTEXT_GROWTH} />);
    const group = screen.getByRole("group", { name: "Usage breakdown" });
    expect(within(group).getByRole("button", { name: /^Context/ }).textContent)
      .toContain("3.1 MB");
  });

  it("refuses to put a dollar figure on it, and says why", () => {
    render(<UsageCallout tools={TOOLS} contextGrowth={CONTEXT_GROWTH} />);
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    expect(screen.getByText(/not by dollars/)).toBeInTheDocument();
    expect(screen.getByText(/before any of its tools ran/)).toBeInTheDocument();
  });

  it("tells an un-backfilled store what to run rather than showing nothing", () => {
    render(<UsageCallout tools={TOOLS} />);
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    expect(screen.getByText(/No result sizes recorded/)).toBeInTheDocument();
    expect(screen.getByText(/chronicle sync --full/)).toBeInTheDocument();
  });

  it("has no average for a tool whose results were never sized", () => {
    render(<UsageCallout tools={TOOLS} contextGrowth={{
      result_chars: 0, calls: 3, measured_calls: 0, tools_total: 1,
      tools: [{ tool_name: "Bash", calls: 3, measured_calls: 0,
                result_chars: 0, share: 0, avg_chars: null }],
    }} />);
    fireEvent.click(screen.getByRole("button", { name: /^Context/ }));
    // Not "0 B per call" — that would claim it returned nothing, which is a
    // different statement from having no measurement.
    expect(screen.getByTitle(/no result sizes recorded/)).toBeInTheDocument();
  });
});
