import { describe, expect, it } from "vitest";
import type { ChronicleSession } from "../../api/types";
import { costByRepo } from "./costByRepo";

function session(overrides: Partial<ChronicleSession> & { session_id: string }): ChronicleSession {
  return {
    project_slug: "-repo", cwd: "/repo", repo_root: "/repo", git_branch: "main", entrypoint: "cli", version: "x",
    title: null, transcript_path: null, transcript_bytes: 0, started_at: 0, ended_at: null, end_reason: null,
    last_activity_at: 0, updated_at: 0, turns: 10, prompts: 2, tool_calls: 0, input_tokens: 0, cache_read_tokens: 0,
    cache_creation_tokens: 0, output_tokens: 100, thinking_tokens: 10, peak_context_tokens: 0, compactions: 0,
    cold_turns: 0, artifacts: 0, subagents: 0, active_ms: 0, models: [], cache_hit_rate: null, peak_context_pct: 0.1,
    context_window: 1_000_000, duration_s: 0, context_tokens: 0, live: false, cost_usd: 1, unpriced_turns: 0,
    lines_added: 0, lines_removed: 0, files_touched: 0,
    ...overrides,
  };
}

// Fixed local-noon epochs so the day-bucketing in `costByRepo` can never
// straddle midnight in whatever timezone the test runner is in.
const DAY_1 = Date.UTC(2026, 8, 1, 12) / 1000;
const DAY_2 = Date.UTC(2026, 8, 2, 12) / 1000;

describe("costByRepo", () => {
  it("buckets cost by day and repo", () => {
    const { series, points } = costByRepo([
      session({ session_id: "a", repo_root: "/repos/foo", started_at: DAY_1, cost_usd: 2 }),
      session({ session_id: "b", repo_root: "/repos/bar", started_at: DAY_1, cost_usd: 3 }),
      session({ session_id: "c", repo_root: "/repos/foo", started_at: DAY_2, cost_usd: 5 }),
    ]);

    expect(series.map((s) => s.key).sort()).toEqual(["/repos/bar", "/repos/foo"]);
    expect(series.find((s) => s.key === "/repos/foo")?.total).toBe(7);
    expect(series.find((s) => s.key === "/repos/bar")?.total).toBe(3);

    expect(points).toHaveLength(2);
    expect(points[0].detail).toBe("2026-09-01");
    expect(points[1].detail).toBe("2026-09-02");
  });

  it("keeps every series present in every point, zero-filled where a repo had no session that day", () => {
    const { points } = costByRepo([
      session({ session_id: "a", repo_root: "/repos/foo", started_at: DAY_1, cost_usd: 2 }),
      session({ session_id: "b", repo_root: "/repos/bar", started_at: DAY_2, cost_usd: 3 }),
    ]);

    const day1 = points.find((p) => p.detail === "2026-09-01")!;
    const day2 = points.find((p) => p.detail === "2026-09-02")!;
    expect(day1.segments.find((s) => s.key === "/repos/bar")?.value).toBe(0);
    expect(day2.segments.find((s) => s.key === "/repos/foo")?.value).toBe(0);
  });

  it("sums multiple sessions in the same repo on the same day", () => {
    const { series } = costByRepo([
      session({ session_id: "a", repo_root: "/repos/foo", started_at: DAY_1, cost_usd: 2 }),
      session({ session_id: "b", repo_root: "/repos/foo", started_at: DAY_1, cost_usd: 1.5 }),
    ]);
    expect(series[0].total).toBeCloseTo(3.5);
  });

  it("groups sessions with no repo_root under a 'No repo' series", () => {
    const { series } = costByRepo([
      session({ session_id: "a", repo_root: null, started_at: DAY_1, cost_usd: 4 }),
    ]);
    expect(series).toHaveLength(1);
    expect(series[0].label).toBe("No repo");
    expect(series[0].total).toBe(4);
  });

  it("folds repos beyond maxSeries into a single 'Other repos' series, ranked by total cost", () => {
    const sessions = ["a", "b", "c", "d"].map((id, i) =>
      session({ session_id: id, repo_root: `/repos/${id}`, started_at: DAY_1, cost_usd: 4 - i })
    );
    const { series, points } = costByRepo(sessions, 2);

    expect(series.map((s) => s.key)).toEqual(["/repos/a", "/repos/b", "__other__"]);
    expect(series.find((s) => s.key === "__other__")?.total).toBeCloseTo(1 + 2);
    // The "Other" segment for the day sums exactly the folded repos.
    expect(points[0].segments.find((s) => s.key === "__other__")?.value).toBeCloseTo(3);
  });

  it("returns no series or points for an empty session list", () => {
    expect(costByRepo([])).toEqual({ series: [], points: [] });
  });

  it("skips sessions with no started_at — they cannot be placed in a day bucket", () => {
    const { points } = costByRepo([
      session({ session_id: "a", repo_root: "/repos/foo", started_at: null, cost_usd: 4 }),
    ]);
    expect(points).toHaveLength(0);
  });
});
