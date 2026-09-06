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
    tools: [{ tool_name: "Bash", calls: 6, sessions: 2 }],
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

describe("<ChroniclePage/>", () => {
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

  it("opens the session drawer from a row", async () => {
    mocked.getChronicleSession.mockResolvedValue({
      ...session({ session_id: "aaaa1111-x", title: "Fix the widget" }),
      cold_turns: 1,
      subagents: [],
      turn_series: [
        { ts: 1, model: "claude-opus-5", context_tokens: 100, input_tokens: 1, cache_read_tokens: 0, cache_creation_tokens: 99, cache_5m_tokens: 99, cache_1h_tokens: 0, output_tokens: 5, thinking_tokens: 0, tool_calls: 1, stop_reason: "end_turn", cold: true, gap_s: null, cost_usd: 0.0007 },
        { ts: 700, model: "claude-opus-5", context_tokens: 120, input_tokens: 1, cache_read_tokens: 99, cache_creation_tokens: 20, cache_5m_tokens: 20, cache_1h_tokens: 0, output_tokens: 5, thinking_tokens: 0, tool_calls: 0, stop_reason: "end_turn", cold: false, gap_s: 699, cost_usd: 0.0003 },
      ],
      tools: [{ tool_name: "Read", calls: 1 }],
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
