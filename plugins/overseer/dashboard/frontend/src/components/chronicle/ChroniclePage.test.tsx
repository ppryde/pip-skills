import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ChronicleSession, ChronicleSummary } from "../../api/types";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    getChronicleSummary: vi.fn(),
    getChronicleSessions: vi.fn(),
    getChronicleSession: vi.fn(),
    getChronicleAgent: vi.fn(),
    syncChronicle: vi.fn(),
    setActiveRoot: vi.fn(),
  };
});

import { useState } from "react";
import * as client from "../../api/client";
import { useChronicle, useChronicleSync } from "../../board/chronicle/useChronicle";
import ChronicleFilterBar from "./ChronicleFilterBar";
import ChroniclePage from "./ChroniclePage";

/** App.tsx's wiring in miniature: the filter state, the fetch, the sync
 * action and the two components they feed. The page itself only reads data
 * now, so exercising filters and Sync means standing the owner up around it
 * — the Sync, All-repos and branch controls here stand in for the top bar's
 * (TopBarChronicle.test.tsx covers those). */
function Harness({ activeRoot, repoScopable }: { activeRoot: string | null; repoScopable: boolean }) {
  const [days, setDays] = useState<number | undefined>(30);
  const [allRepos, setAllRepos] = useState(false);
  const [branch, setBranch] = useState<string | null>(null);
  const scope = allRepos || !repoScopable ? "all" : "repo";
  const data = useChronicle(activeRoot, { days, scope, branch }, true);
  const { sync, syncing, note } = useChronicleSync(data.refresh);
  return (
    <>
      <button type="button" onClick={() => void sync()} disabled={syncing}>
        Sync
      </button>
      <button type="button" onClick={() => setAllRepos(true)}>
        All repos
      </button>
      <button type="button" onClick={() => setBranch("feat/x")}>
        Branch feat/x
      </button>
      <ChronicleFilterBar days={days} onDays={setDays} syncNote={note} filtersOpen />
      <ChroniclePage
        summary={data.summary}
        sessions={data.sessions}
        loading={data.loading}
        error={data.error}
        onRetry={() => void data.refresh()}
      />
    </>
  );
}

function session(overrides: Partial<ChronicleSession> & { session_id: string }): ChronicleSession {
  return {
    project_slug: "-repo",
    cwd: "/repo",
    repo_root: "/repos/pip-skills",
    git_branch: "main",
    entrypoint: "cli",
    version: "2.1.258",
    title: null,
    transcript_path: null,
    transcript_bytes: 2048,
    started_at: 1_788_256_800,
    ended_at: null,
    end_reason: null,
    last_activity_at: 1_788_260_400,
    updated_at: 0,
    turns: 5,
    prompts: 2,
    tool_calls: 3,
    input_tokens: 10,
    cache_read_tokens: 1000,
    cache_creation_tokens: 100,
    output_tokens: 400,
    thinking_tokens: 50,
    peak_context_tokens: 1110,
    compactions: 0,
    cold_turns: 1,
    artifacts: 0,
    subagents: 0,
    active_ms: 0,
    models: ["claude-opus-5"],
    cache_hit_rate: 0.9,
    peak_context_pct: 0.00555,
    context_window: 200_000,
    duration_s: 3600,
    context_tokens: 1110,
    live: false,
    cost_usd: 0.42,
    unpriced_turns: 0,
    lines_added: 0,
    lines_removed: 0,
    files_touched: 0,
    ...overrides,
  };
}

function summary(): ChronicleSummary {
  return {
    totals: {
      sessions: 2, turns: 12, prompts: 4, tool_calls: 6, input_tokens: 20, cache_read_tokens: 2000,
      cache_creation_tokens: 200, output_tokens: 900, thinking_tokens: 100, compactions: 1,
      subagents: 1, active_ms: 120_000, transcript_bytes: 4096, live: 1, cold_turns: 2, artifacts: 1,
      cache_hit_rate: 0.901, cache_5m_tokens: 50, cache_1h_tokens: 150,
      peak_context_tokens: 120_000, peak_context_pct: 0.6, context_window: 200_000,
      cost_usd: 12.3, unpriced_turns: 0, pricing_as_of: "2026-06-24",
    },
    by_day: [{ day: "2026-09-01", sessions: 2, turns: 12, input_tokens: 20, cache_read_tokens: 2000, cache_creation_tokens: 200, output_tokens: 900, cold_turns: 2, peak_context_tokens: 1110, peak_context_pct: 0.00555, cache_hit_rate: 0.901, cost_usd: 12.3, unpriced_turns: 0 }],
    by_model: [{ model: "claude-opus-5", turns: 12, sessions: 2, input_tokens: 20, cache_read_tokens: 2000, cache_creation_tokens: 200, cache_5m_tokens: 50, cache_1h_tokens: 150, output_tokens: 900, cost_usd: 12.3 }],
    tools: [{ tool_name: "Bash", calls: 6, sessions: 2, result_chars: 1200, median_s: 2.5, subagent_calls: 3 }],
    mcp: {
      calls: 4, sessions: 1, result_chars: 900,
      by_provenance: { plugin: 2, connector: 1, local: 1 },
      servers: [
        { server: "plugin_playwright_playwright", provenance: "plugin", tools: 1, calls: 2, sessions: 1, result_chars: 500, median_s: 1.5, subagent_calls: 0 },
        { server: "claude-in-chrome", provenance: "local", tools: 1, calls: 1, sessions: 1, result_chars: 400, median_s: 1.5, subagent_calls: 0 },
      ],
      tools: [],
    },
    plugins: {
      calls: 3, sessions: 1,
      items: [
        { plugin: "playwright", kind: "mcp", calls: 2, sessions: 1, result_chars: 0, median_s: null, subagent_calls: 0 },
        { plugin: "tribunal", kind: "skill", calls: 1, sessions: 1, result_chars: 0, median_s: null, subagent_calls: 0 },
      ],
    },
    artifacts: [
      // A distinct session_title: the list echoes it as a button, and the
      // tests below look "Fix the widget" up by text.
      { session_id: "aaaa1111-x", session_title: "Report session", ts: 1_788_260_000, first_ts: 1_788_259_000,
        url: "https://claude.ai/code/artifact/abc", title: "Widget report", description: "A tour", favicon: "📊", publishes: 3 },
    ],
    shape: {
      turns: { p50: 6, p90: 7, max: 7, mean: 6 },
      prompts: { p50: 2, p90: 2, max: 2, mean: 2 },
      duration_s: { p50: 3600, p90: 3600, max: 3600, mean: 3600 },
      transcript_bytes: { p50: 2048, p90: 2048, max: 2048, mean: 2048 },
      peak_context_tokens: { p50: 1110, p90: 1110, max: 1110, mean: 1110 },
      cost_usd: { p50: 0.42, p90: 0.42, max: 0.42, mean: 0.42 },
    },
  };
}

const mocked = client as unknown as {
  getChronicleSummary: ReturnType<typeof vi.fn>;
  getChronicleSessions: ReturnType<typeof vi.fn>;
  getChronicleSession: ReturnType<typeof vi.fn>;
  getChronicleAgent: ReturnType<typeof vi.fn>;
  syncChronicle: ReturnType<typeof vi.fn>;
  setActiveRoot: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  mocked.getChronicleSummary.mockResolvedValue(summary());
  mocked.getChronicleSessions.mockResolvedValue({
    sessions: [
      session({ session_id: "aaaa1111-x", title: "Fix the widget", turns: 7 }),
      session({ session_id: "bbbb2222-x", turns: 5, live: true }),
    ],
  });
  mocked.syncChronicle.mockResolvedValue({ scanned: 3, changed: 1, lines: 12, sessions: ["aaaa1111-x"], synced_at: 1 });
});

afterEach(() => {
  vi.clearAllMocks();
});

/** Position of the Subagents cell in a session row: the two leading columns
 * (Session, Repo · branch) plus its place among the sortable ones. Named so
 * the assertion reads as a column rather than a magic number. */
const COLUMN_INDEX_SUBAGENTS = 2 + 5;

/** The page renders from props alone; these tests drive it directly rather
 * than through the fetch harness, since only the scope prop is under test. */
function pageProps(sessions: ChronicleSession[]) {
  return { summary: summary(), sessions, loading: false, error: null, onRetry: () => {} };
}

describe("<ChroniclePage/>", () => {
  it("puts tools, MCP and plugins behind one usage callout", async () => {
    render(<Harness activeRoot="/repos/pip-skills" repoScopable />);
    expect(await screen.findByRole("heading", { name: "Usage breakdown" })).toBeInTheDocument();
    // Tools first; the other two are a click away, and full width means the
    // server name arrives whole rather than clipped.
    expect(screen.getByText("Bash")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^MCP/ }));
    expect(screen.getByText("plugin_playwright_playwright")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Plugins/ }));
    // A plugin's MCP calls are counted on BOTH tabs — the deliberate overlap.
    expect(screen.getByText("playwright · mcp")).toBeInTheDocument();
    expect(screen.getByText("tribunal · skill")).toBeInTheDocument();
  });

  it("renders tiles, charts and the session table from the summary", async () => {
    render(<Harness activeRoot="/repos/pip-skills" repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    expect(screen.getByRole("table", { name: "Sessions" })).toBeInTheDocument();
    // Nowrap-everywhere fix (mobile horizontal scroll, not text-wrap collapse):
    // scoped to this table alone, never the drawer's other .chr-table uses.
    expect(screen.getByRole("table", { name: "Sessions" })).toHaveClass("chr-table--sessions");
    expect(screen.getByText("Scroll sideways for more columns →")).toBeInTheDocument();
    expect(screen.getByText("1 live")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Context tokens per day" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Peak context tokens per day" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Cache hit rate per day" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "API-equivalent cost per day" })).toBeInTheDocument();
    // Cost: the tile (its pricing caveat lives behind the label's
    // InfoTooltip, never as a footnote that wraps), and a Cost column per
    // session.
    expect(screen.getAllByText("$12.30").length).toBeGreaterThan(0); // tile + the chart's data table
    expect(screen.getByText("API costs")).toBeInTheDocument();
    expect(screen.queryByText("at list prices, Jun 2026")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About API costs" })).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Sessions" })).getAllByText("$0.42")).toHaveLength(2);
    // Both gauges render: cache warmth and peak context against its window.
    expect(screen.getByRole("img", { name: "Cache hit rate: 90%" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Peak context used: 60%" })).toBeInTheDocument();
    expect(screen.getByText("warm")).toBeInTheDocument();
    expect(screen.getByText("120k of 200k")).toBeInTheDocument();
    // Counsel: the window's efficiency insights, with a verdict word each.
    expect(screen.getByText("Counsel from the elders")).toBeInTheDocument();
    expect(screen.getByText("Read-to-write ratio")).toBeInTheDocument();
    expect(screen.getAllByText("In this window").length).toBeGreaterThan(0);
    expect(screen.getByText("Average cost per turn by model")).toBeInTheDocument();
    expect(screen.getByText("one model")).toBeInTheDocument(); // only opus-5 in the fixture
    expect(screen.getByText("Cost per prompt")).toBeInTheDocument();
    expect(screen.getByText("Thinking share of output")).toBeInTheDocument();
    // Levers are there but folded away: a closed <details> per row.
    const disclosures = document.querySelectorAll(".chr-counsel__disclosure");
    expect(disclosures.length).toBe(4);
    disclosures.forEach((d) => expect(d).not.toHaveAttribute("open"));
    expect(screen.getAllByText("What you could do").length).toBe(4);
    // The two breakdowns that used to be tile footnotes are rings now: the
    // thinking share of output, and the cache write split by TTL.
    expect(screen.getByRole("img", { name: "Where output went" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Cache written by TTL" })).toBeInTheDocument();
    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.getByText("1h cache")).toBeInTheDocument();
    expect(screen.queryByText(/thinking$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/at 1h/)).not.toBeInTheDocument();
    // Artifacts: the tile (no footnote — the number is the whole story), and
    // the page list with a real link + publish count.
    expect(screen.queryByText("distinct pages published")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Widget report" });
    expect(link).toHaveAttribute("href", "https://claude.ai/code/artifact/abc");
    expect(screen.getByText(/3 publishes/)).toBeInTheDocument();
    expect(screen.getAllByText("opus-5").length).toBeGreaterThan(0); // turns-by-model bar + counsel row
    expect(screen.getAllByText("bbbb2222").length).toBeGreaterThan(0);
    expect(mocked.setActiveRoot).toHaveBeenCalledWith("/repos/pip-skills");
    expect(mocked.getChronicleSummary).toHaveBeenCalledWith({ days: 30, scope: "repo", branch: null });
  });

  it("re-fetches with the chosen window, scope and branch", async () => {
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(mocked.getChronicleSummary).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "All time" }));
    await waitFor(() =>
      expect(mocked.getChronicleSummary).toHaveBeenLastCalledWith({ days: undefined, scope: "repo", branch: null })
    );
    fireEvent.click(screen.getByRole("button", { name: "All repos" }));
    await waitFor(() =>
      expect(mocked.getChronicleSummary).toHaveBeenLastCalledWith({ days: undefined, scope: "all", branch: null })
    );
    fireEvent.click(screen.getByRole("button", { name: "Branch feat/x" }));
    await waitFor(() =>
      expect(mocked.getChronicleSessions).toHaveBeenLastCalledWith({ days: undefined, scope: "all", branch: "feat/x" })
    );
  });

  it("pins scope to all repos when the repo is not scopable", async () => {
    render(<Harness activeRoot="/unbegun" repoScopable={false} />);
    await waitFor(() =>
      expect(mocked.getChronicleSummary).toHaveBeenCalledWith({ days: 30, scope: "all", branch: null })
    );
  });

  it("Sync posts, reports, and refreshes", async () => {
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(mocked.getChronicleSummary).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 session updated (12 new lines)"));
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(1);
    expect(mocked.getChronicleSummary).toHaveBeenCalledTimes(2);
  });

  it("shows the blank-chronicle prompt when there is no store", async () => {
    mocked.getChronicleSummary.mockResolvedValue({ totals: null });
    mocked.getChronicleSessions.mockResolvedValue({ sessions: [] });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText(/chronicle is blank/i)).toBeInTheDocument());
  });

  it("sorts the table when a column header is clicked", async () => {
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    const table = () => within(screen.getByRole("table", { name: "Sessions" }));
    fireEvent.click(table().getByRole("button", { name: /^Turns/ }));
    let rows = table().getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Fix the widget"); // 7 turns first, desc
    fireEvent.click(table().getByRole("button", { name: /^Turns/ }));
    rows = table().getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("bbbb2222");
  });

  it("shows what each session changed, ranked by lines moved", async () => {
    mocked.getChronicleSessions.mockResolvedValue({
      sessions: [
        session({ session_id: "aaaa1111-x", title: "Fix the widget",
                  files_touched: 13, lines_added: 720, lines_removed: 179 }),
        session({ session_id: "bbbb2222-x", files_touched: 32,
                  lines_added: 995, lines_removed: 87 }),
      ],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    const table = () => within(screen.getByRole("table", { name: "Sessions" }));
    expect(table().getByText("+720 / -179")).toBeInTheDocument();

    // Ranked on added PLUS removed: a big deletion is as much editing as a
    // big addition, so 995/87 leads 720/179.
    fireEvent.click(table().getByRole("button", { name: /^Lines/ }));
    expect(table().getAllByRole("row").slice(1)[0]).toHaveTextContent("bbbb2222");
    fireEvent.click(table().getByRole("button", { name: /^Files/ }));
    expect(table().getAllByRole("row").slice(1)[0]).toHaveTextContent("bbbb2222");
  });

  it("em-dashes churn rather than claiming a session changed nothing", async () => {
    // Zero is what a pruned transcript leaves behind as well as what a
    // session that edited nothing leaves — the store cannot tell them apart,
    // so the table must not read as "0 lines changed".
    mocked.getChronicleSessions.mockResolvedValue({
      sessions: [session({ session_id: "aaaa1111-x", title: "Fix the widget" })],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    const row = within(screen.getByRole("table", { name: "Sessions" })).getAllByRole("row")[1];
    expect(row).not.toHaveTextContent("+0 / -0");
  });

  it("shows a Subagents column, em-dashing the sessions that delegated none", async () => {
    mocked.getChronicleSessions.mockResolvedValue({
      sessions: [
        session({ session_id: "aaaa1111-x", title: "Fix the widget", subagents: 4 }),
        session({ session_id: "bbbb2222-x", subagents: 0 }),
      ],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    const table = () => within(screen.getByRole("table", { name: "Sessions" }));
    expect(table().getByRole("button", { name: /^Subagents/ })).toBeInTheDocument();

    // Sorted by Subagents desc: the delegating session leads, and the one
    // that spawned none reads "—" rather than a bare 0.
    fireEvent.click(table().getByRole("button", { name: /^Subagents/ }));
    const rows = table().getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Fix the widget");
    // By cell index, not by text: Artifacts em-dashes a zero too, so a bare
    // getByText("—") matches two cells in the same row.
    const subagentCell = (row: HTMLElement) =>
      within(row).getAllByRole("cell")[COLUMN_INDEX_SUBAGENTS];
    expect(subagentCell(rows[0])).toHaveTextContent("4");
    expect(subagentCell(rows[1])).toHaveTextContent("—");
  });

  it("filters the table to live sessions, without touching the tiles above", async () => {
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    const table = () => within(screen.getByRole("table", { name: "Sessions" }));
    const activity = () => within(screen.getByRole("group", { name: "Session activity" }));

    // One of the two fixture sessions is live, and the toggle says so.
    expect(table().getAllByRole("row").slice(1)).toHaveLength(2);
    fireEvent.click(activity().getByRole("button", { name: "Live (1)" }));

    const rows = table().getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("bbbb2222");
    expect(rows[0]).not.toHaveTextContent("Fix the widget");
    // The summary is fetched, not derived from the rows, so narrowing the
    // table must not restate the totals: still "1 live" of 2 sessions.
    expect(screen.getByText("1 live")).toBeInTheDocument();
    expect(mocked.getChronicleSessions).toHaveBeenCalledTimes(1); // filter is local, no re-fetch

    fireEvent.click(activity().getByRole("button", { name: "All" }));
    expect(table().getAllByRole("row").slice(1)).toHaveLength(2);
  });

  it("disables the live filter when nothing is live", async () => {
    mocked.getChronicleSessions.mockResolvedValue({
      sessions: [session({ session_id: "aaaa1111-x", title: "Fix the widget", live: false })],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    const activity = within(screen.getByRole("group", { name: "Session activity" }));
    // Enabled, it could only ever empty the table — so it reads "Live", uncounted.
    expect(activity.getByRole("button", { name: "Live" })).toBeDisabled();
  });

  it("renders the usage callout in the session drawer", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget" }),
      cold_turns: 0,
      subagents: [],
      turn_series: [],
      tools: [{ tool_name: "Read", calls: 1, result_chars: 400, median_s: 1, subagent_calls: 0 }],
      compactions_at: [],
      artifacts: [],
      biggest_jumps: [],
      mcp: {
        calls: 2, result_chars: 100,
        by_provenance: { plugin: 1, connector: 1 },
        servers: [
          { server: "plugin_linear_linear", provenance: "plugin", tools: 1, calls: 1, result_chars: 60, median_s: 1.5, subagent_calls: 0 },
          { server: "claude_ai_Notion", provenance: "connector", tools: 1, calls: 1, result_chars: 40, median_s: 1.5, subagent_calls: 0 },
        ],
        tools: [],
      },
      plugins: {
        calls: 2,
        items: [
          { plugin: "linear", kind: "mcp", calls: 1, result_chars: 0, median_s: null, subagent_calls: 0 },
          { plugin: "overseer", kind: "skill", calls: 1, result_chars: 0, median_s: null, subagent_calls: 0 },
        ],
      },
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Fix the widget" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    // Scoped to the dialog: the page behind it carries a callout of its own.
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.click(dialog.getByRole("button", { name: /^MCP/ }));
    expect(dialog.getByText("plugin_linear_linear")).toBeInTheDocument();
    expect(dialog.getByText("claude_ai_Notion")).toBeInTheDocument();

    fireEvent.click(dialog.getByRole("button", { name: /^Plugins/ }));
    expect(dialog.getByText("overseer · skill")).toBeInTheDocument();
  });

  it("shows a session's own churn, attribution and delegation in the drawer", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget",
                   files_touched: 13, lines_added: 720, lines_removed: 179 }),
      cold_turns: 0,
      subagents: [],
      turn_series: [],
      tools: [{ tool_name: "Read", calls: 1, result_chars: 400, median_s: 1, subagent_calls: 0 }],
      compactions_at: [],
      artifacts: [],
      biggest_jumps: [],
      attribution: {
        turns: 427, attributed_turns: 17, cost_usd: 1.5, unattributed_cost_usd: 8.5,
        plugins: [{ name: "superpowers", turns: 17, context_tokens: 1000,
                    output_tokens: 50, cost_usd: 1.5, skills: 1 }],
        skills: [{ name: "superpowers:brainstorming", turns: 17, context_tokens: 1000,
                   output_tokens: 50, cost_usd: 1.5, plugin: "superpowers" }],
        agents: [], mcp: [],
      },
      delegation: {
        turns: 427, subagent_turns: 233, output_tokens: 183_669,
        subagent_output_tokens: 29_263, tool_calls: 446, subagent_tool_calls: 245,
      },
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Fix the widget" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    const dialog = within(screen.getByRole("dialog"));

    expect(dialog.getByText("+720 / -179")).toBeInTheDocument();
    expect(dialog.getByText("Files touched")).toBeInTheDocument();

    // Attribution reaches the drawer now, so the Plugins tab answers "what
    // did this session's tokens go to" rather than counting invocations.
    fireEvent.click(dialog.getByRole("button", { name: /^Skills/ }));
    expect(dialog.getByText("superpowers:brainstorming")).toBeInTheDocument();

    // 233 of 427 turns ran inside a subagent — worth stating per session,
    // not only for the whole window.
    expect(dialog.getByText("Delegation")).toBeInTheDocument();
    expect(dialog.getByLabelText(/^Turns: 55% delegated/)).toBeInTheDocument();
  });

  it("omits the delegation panel for a session that spawned nothing", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget" }),
      cold_turns: 0, subagents: [], turn_series: [], tools: [],
      compactions_at: [], artifacts: [], biggest_jumps: [],
      delegation: {
        turns: 10, subagent_turns: 0, output_tokens: 100,
        subagent_output_tokens: 0, tool_calls: 5, subagent_tool_calls: 0,
      },
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Fix the widget" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    // Three bars all reading 0% say nothing; the panel stays away.
    expect(within(screen.getByRole("dialog")).queryByText("Delegation")).not.toBeInTheDocument();
  });

  it("badges the plan a session ran on, and shows nothing when it is unknown", async () => {
    mocked.getChronicleSessions.mockResolvedValue({
      sessions: [
        session({ session_id: "aaaa1111-x", title: "On Max", plan_organization_type: "claude_max" }),
        session({ session_id: "bbbb2222-x", title: "No plan", plan_organization_type: null }),
      ],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("On Max")).toBeInTheDocument());
    const table = () => within(screen.getByRole("table", { name: "Sessions" }));
    const rows = table().getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Max")).toBeInTheDocument();
    // The unknown case renders NO badge — never the word "unknown".
    expect(within(rows[1]).queryByText(/unknown/i)).not.toBeInTheDocument();
    expect(within(rows[1]).queryByText("Max")).not.toBeInTheDocument();
  });

  it("offers a plan filter only across all repos, and only when plans actually differ", async () => {
    const mixed = {
      sessions: [
        session({ session_id: "aaaa1111-x", title: "On Max", plan_organization_type: "claude_max" }),
        session({ session_id: "bbbb2222-x", title: "On Ent", plan_organization_type: "claude_enterprise" }),
      ],
    };
    mocked.getChronicleSessions.mockResolvedValue(mixed);

    // Within one repo the sessions are near-always one plan, so the control
    // would be a permanent no-op: absent by design, not merely empty.
    const one = render(<ChroniclePage {...pageProps(mixed.sessions)} scope="repo" />);
    expect(screen.queryByRole("group", { name: "Plan" })).not.toBeInTheDocument();
    one.unmount();

    render(<ChroniclePage {...pageProps(mixed.sessions)} scope="all" />);
    const plan = within(screen.getByRole("group", { name: "Plan" }));
    fireEvent.click(plan.getByRole("button", { name: "Enterprise (1)" }));
    const rows = within(screen.getByRole("table", { name: "Sessions" })).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("On Ent");
  });

  it("hides the plan filter when every session shares one plan", () => {
    // One plan is a label, not a choice.
    const same = [
      session({ session_id: "aaaa1111-x", plan_organization_type: "claude_max" }),
      session({ session_id: "bbbb2222-x", plan_organization_type: "claude_max" }),
    ];
    render(<ChroniclePage {...pageProps(same)} scope="all" />);
    expect(screen.queryByRole("group", { name: "Plan" })).not.toBeInTheDocument();
  });

  it("opens a subagent over the session drawer, and unwinds one layer at a time", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget" }),
      cold_turns: 0, turn_series: [], tools: [], compactions_at: [],
      artifacts: [], biggest_jumps: [],
      subagents: [
        { agent_id: "a11111111aaaa", turns: 10, context_tokens: 1000, output_tokens: 500,
          tool_calls: 4, first_ts: 1, last_ts: 2, task: "Find the auth flow",
          agent_type: "Explore" },
        { agent_id: "a22222222bbbb", turns: 4, context_tokens: 100, output_tokens: 50,
          tool_calls: 1, first_ts: 1, last_ts: 2, task: "Audit the ORM",
          agent_type: "general-purpose" },
      ],
    });
    mocked.getChronicleAgent.mockResolvedValue({
      session_id: "aaaa1111-x", agent_id: "a11111111aaaa", task: "Find the auth flow",
      agent_type: "Explore", turns: 10, context_tokens: 1000, input_tokens: 10,
      cache_read_tokens: 900, cache_creation_tokens: 90, output_tokens: 500,
      thinking_tokens: 20, tool_calls: 4, peak_context_tokens: 900,
      first_ts: 1, last_ts: 2, duration_s: 1, cache_hit_rate: 0.9,
      cost_usd: 0.42, unpriced_turns: 0, turn_series: [], tools: [], artifacts: [],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Fix the widget" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    // The session's Subagents table names each agent by its task, and is the
    // way in to the second sheet.
    fireEvent.click(screen.getByRole("button", { name: "Find the auth flow" }));
    await waitFor(() =>
      expect(screen.getByTestId("subagent-drawer-overlay")).toBeInTheDocument());
    // Layered, not replacing: the session drawer is still mounted beneath.
    expect(screen.getByTestId("chronicle-drawer-overlay")).toBeInTheDocument();

    // Escape unwinds ONE layer — the subagent closes, the session stays.
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("subagent-drawer-overlay")).not.toBeInTheDocument());
    expect(screen.getByTestId("chronicle-drawer-overlay")).toBeInTheDocument();

    // A second Escape closes the session drawer.
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("chronicle-drawer-overlay")).not.toBeInTheDocument());
  });

  it("opens the session drawer from a row", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget" }),
      cold_turns: 1,
      subagents: [],
      turn_series: [
        { ts: 1, model: "claude-opus-5", context_tokens: 100, input_tokens: 1, cache_read_tokens: 0, cache_creation_tokens: 99, cache_5m_tokens: 99, cache_1h_tokens: 0, output_tokens: 5, thinking_tokens: 0, tool_calls: 1, stop_reason: "end_turn", cold: true, gap_s: null, cost_usd: 0.0007 },
        { ts: 700, model: "claude-opus-5", context_tokens: 120, input_tokens: 1, cache_read_tokens: 99, cache_creation_tokens: 20, cache_5m_tokens: 20, cache_1h_tokens: 0, output_tokens: 5, thinking_tokens: 0, tool_calls: 0, stop_reason: "end_turn", cold: false, gap_s: 699, cost_usd: 0.0003 },
      ],
      tools: [{ tool_name: "Read", calls: 1, result_chars: 400, median_s: 1, subagent_calls: 0 }],
      compactions_at: [],
      artifacts: [
        { session_id: "aaaa1111-x", ts: 5, first_ts: 5, url: null, title: "lost-page", description: null, favicon: null, publishes: 1 },
      ],
      biggest_jumps: [
        { turn: 2, ts: 700, context_tokens: 120, delta_tokens: 20, output_tokens: 5, cold: false, tool_calls: 0,
          landed: [{ tool_name: "Read", chars: 4200 }], landed_chars: 4200 },
        { turn: 1, ts: 1, context_tokens: 100, delta_tokens: 100, output_tokens: 5, cold: true, tool_calls: 1,
          landed: [], landed_chars: 0 },
      ],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Fix the widget" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(mocked.getChronicleSession).toHaveBeenCalledWith("aaaa1111-x");
    expect(screen.getByRole("img", { name: "Context tokens per turn" })).toBeInTheDocument();
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText("$0.42")).toBeInTheDocument();
    // Renamed drawer tiles (WF chronicle mobile-density pass): shorter
    // labels, no footnote — the unpriced/list-price caveat now lives behind
    // an InfoTooltip instead, so it survives the density cut.
    expect(dialog.getByText("Total ctx")).toBeInTheDocument();
    expect(dialog.getByText("API costs")).toBeInTheDocument();
    expect(dialog.queryByText("Context processed")).not.toBeInTheDocument();
    expect(dialog.queryByText("API-equivalent cost")).not.toBeInTheDocument();
    expect(dialog.queryByText("at list prices")).not.toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "About API costs" }));
    expect(dialog.getByText(/comparison yardstick, not a bill/)).toBeInTheDocument();
    // Marks: turn 1 is cold; turn 2, the first row of biggest_jumps, is THE
    // biggest jump — only one gets a peak. Its 11-minute gap is tooltip-only.
    // Named in the legend, never glyph-only.
    const kinds = screen.getAllByTestId("chr-event").map((g) => g.getAttribute("data-kind")).sort();
    expect(kinds).toEqual(["cold", "jump"]);
    expect(screen.getByRole("list", { name: "Marks" })).toHaveTextContent("cold cache turn");
    expect(screen.getByText("Read")).toBeInTheDocument();
    // Biggest jumps: attribution text and the cold tag; a url-less artifact
    // renders as a dotted name, not a link.
    const jumps = within(screen.getByRole("table", { name: "Biggest jumps" }));
    expect(jumps.getByText("Read 4.2k chars")).toBeInTheDocument();
    expect(jumps.getByText("cold")).toBeInTheDocument();
    expect(screen.getByText("lost-page")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "lost-page" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("drawer's API costs tile never reads as free when every turn is unpriced", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget" }),
      cost_usd: 0,
      unpriced_turns: 3,
      turn_series: [],
      subagents: [],
      tools: [],
      compactions_at: [],
      artifacts: [],
      biggest_jumps: [],
    });
    render(<Harness activeRoot={null} repoScopable />);
    await waitFor(() => expect(screen.getByText("Fix the widget")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Fix the widget" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText("unpriced (3)")).toBeInTheDocument();
    expect(dialog.queryByText("$0")).not.toBeInTheDocument();
  });
});
