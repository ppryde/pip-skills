import { describe, expect, it } from "vitest";
import type { ChronicleModel, ChronicleSession, ChronicleTotals } from "../../api/types";
import type { InsightInputs } from "./insights";
import {
  costPerPrompt,
  costPerTurnByModel,
  delegationBalance,
  readWriteRatio,
  reworkShare,
  thinkingShare,
  windowFill,
  windowInsights,
} from "./insights";

function totals(overrides: Partial<ChronicleTotals> = {}): ChronicleTotals {
  return {
    sessions: 2, turns: 100, prompts: 10, tool_calls: 50, input_tokens: 1000, cache_read_tokens: 20_000_000,
    cache_creation_tokens: 1_000_000, output_tokens: 50_000, thinking_tokens: 10_000, compactions: 0,
    subagents: 0, active_ms: 0, transcript_bytes: 0, live: 0, cold_turns: 0, artifacts: 0,
    cache_hit_rate: 0.9, cache_5m_tokens: 0, cache_1h_tokens: 0,
    peak_context_tokens: 0, peak_context_pct: 0, context_window: 1_000_000,
    cost_usd: 0, unpriced_turns: 0, pricing_as_of: "2026-06-24",
    ...overrides,
  };
}

function model(overrides: Partial<ChronicleModel> & { model: string }): ChronicleModel {
  return {
    turns: 10, sessions: 1, input_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0,
    cache_5m_tokens: 0, cache_1h_tokens: 0, output_tokens: 0, cost_usd: 1,
    ...overrides,
  };
}

function session(overrides: Partial<ChronicleSession> & { session_id: string }): ChronicleSession {
  return {
    project_slug: "-repo", cwd: "/repo", repo_root: "/repo", git_branch: "main", entrypoint: "cli", version: "x",
    title: null, transcript_path: null, transcript_bytes: 0, started_at: 0, ended_at: null, end_reason: null,
    last_activity_at: 0, updated_at: 0, turns: 10, prompts: 2, tool_calls: 0, input_tokens: 0, cache_read_tokens: 0,
    cache_creation_tokens: 0, output_tokens: 100, thinking_tokens: 10, peak_context_tokens: 0, compactions: 0,
    cold_turns: 0, artifacts: 0, subagents: 0, active_ms: 0, models: [], cache_hit_rate: null, peak_context_pct: 0.1,
    context_window: 1_000_000, duration_s: 0, context_tokens: 0, live: false, cost_usd: 1, unpriced_turns: 0,
    ...overrides,
  };
}

function inputs(overrides: Partial<InsightInputs> = {}): InsightInputs {
  return { totals: totals(), models: [], shape: null, sessions: [], ...overrides };
}

describe("readWriteRatio", () => {
  it("reduces to lowest terms with 1 on the written side", () => {
    expect(readWriteRatio(21_001_000, 50_000)).toBe("420 : 1");
    expect(readWriteRatio(300, 100)).toBe("3 : 1");
    expect(readWriteRatio(50, 100)).toBe("1 : 2"); // would-be fraction flips instead
    expect(readWriteRatio(0, 100)).toBe("—");
  });
});

describe("windowFill", () => {
  it("headlines the read-to-write ratio and bands on the window fill behind it", () => {
    // 21,001,000 context / 50,000 output = 420 : 1; 210k per turn of a 1M window → 21%, lean
    const i = windowFill(inputs());
    expect(i.value).toBe("420 : 1");
    expect(i.verdict).toBe("good");
    expect(i.verdictWord).toBe("lean");
    // 50,000 output / 100 turns = 500 written per turn; 210k / 500 = 420.
    expect(i.detail).toBe("a typical turn read 210k and wrote 500; that read is 21% of the 1M window");
  });

  it("bands by share of the window at a quarter and a half", () => {
    expect(windowFill(inputs({ totals: totals({ cache_read_tokens: 35_000_000 }) })).verdictWord).toBe("typical"); // 36%
    expect(windowFill(inputs({ totals: totals({ cache_read_tokens: 60_000_000 }) })).verdictWord).toBe("heavy"); // 61%
  });

  it("keeps the ratio but cannot band when the window is unknown", () => {
    const i = windowFill(inputs({ totals: totals({ context_window: 0 }) }));
    expect(i.value).toBe("420 : 1");
    expect(i.verdict).toBe("good");
    expect(i.detail).toBe("a typical turn read 210k and wrote 500");
  });

  it("offers more levers as the verdict worsens, clearing between tasks first", () => {
    const lean = windowFill(inputs());
    const typical = windowFill(inputs({ totals: totals({ cache_read_tokens: 35_000_000 }) }));
    const heavy = windowFill(inputs({ totals: totals({ cache_read_tokens: 60_000_000 }) }));
    expect(lean.resolutions?.map((r) => r.title)).toEqual(["Clear between tasks"]);
    expect(typical.resolutions).toHaveLength(3);
    expect(heavy.resolutions).toHaveLength(5);
    expect(heavy.resolutions?.[0].title).toBe("Clear between tasks");
  });

  it("mines the window's sessions for facts about the figure", () => {
    const i = windowFill(
      inputs({
        totals: totals({ compactions: 3, subagents: 4 }),
        sessions: [
          session({ session_id: "a", title: "Big one", peak_context_pct: 0.84, turns: 60, compactions: 2 }),
          session({ session_id: "b", peak_context_pct: 0.3 }),
          session({ session_id: "c", peak_context_pct: 0.55, compactions: 1 }),
        ],
      })
    );
    expect(i.facts).toEqual([
      "2 of 3 sessions pushed past half the window.",
      "Largest: Big one reached 84% over 60 turns.",
      "2 sessions compacted, 3 compactions in all.",
      "4 subagents ran in this window; their turns are counted here too.",
    ]);
  });

  it("has nothing to say without output", () => {
    const i = windowFill(inputs({ totals: totals({ output_tokens: 0 }) }));
    expect(i.value).toBe("—");
    expect(i.verdict).toBe("none");
    expect(i.resolutions).toBeUndefined();
  });
});

describe("costPerTurnByModel", () => {
  it("ranks priced models by cost per turn and blends the headline", () => {
    const i = costPerTurnByModel(
      inputs({
        models: [
          model({ model: "claude-sonnet-5", turns: 80, cost_usd: 4 }), // $0.05/turn
          model({ model: "claude-opus-5", turns: 20, cost_usd: 8 }), // $0.40/turn
          model({ model: "claude-mystery", turns: 5, cost_usd: null }),
        ],
      })
    );
    expect(i.rows?.map((r) => r.label)).toEqual(["opus-5", "sonnet-5"]);
    expect(i.rows?.[0].value).toBe("$0.40");
    // Share is of ALL turns, unpriced ones included: 20 of 105.
    expect(i.rows?.map((r) => r.share)).toEqual(["19%", "76%"]);
    expect(i.rowHeadings).toEqual({ value: "avg / turn", share: "of turns" });
    expect(i.value).toBe("$0.12"); // (4 + 8) / 100 priced turns
    expect(i.detail).toMatch(/blended average over 100 priced turns/);
    expect(i.verdictWord).toBe("tiered"); // 8× spread, but opus took 20% of turns
    // A healthy mix is not told to route work it already routes.
    expect(i.resolutions?.map((r) => r.title)).toEqual(["Pin the subagent model"]);
  });

  it("calls it top-heavy when the dear model does most of the turns, with the full list", () => {
    const i = costPerTurnByModel(
      inputs({
        models: [
          model({ model: "claude-sonnet-5", turns: 20, cost_usd: 1 }),
          model({ model: "claude-opus-5", turns: 80, cost_usd: 32 }),
        ],
      })
    );
    expect(i.verdict).toBe("poor");
    expect(i.counsel).toMatch(/sonnet-5/);
    expect(i.resolutions?.map((r) => r.title)).toContain("Use Sonnet for the routine turns");
    expect(i.resolutions).toHaveLength(4);
  });

  it("is flat when the models cost about the same", () => {
    const i = costPerTurnByModel(
      inputs({ models: [model({ model: "a", turns: 10, cost_usd: 1 }), model({ model: "b", turns: 10, cost_usd: 1.5 })] })
    );
    expect(i.verdictWord).toBe("flat");
  });

  it("names the dearest session and the unpriced turns as facts", () => {
    const i = costPerTurnByModel(
      inputs({
        models: [model({ model: "a" })],
        totals: totals({ unpriced_turns: 7 }),
        sessions: [session({ session_id: "x", title: "Cheap", cost_usd: 1 }), session({ session_id: "y", title: "Dear", cost_usd: 9, turns: 42 })],
      })
    );
    expect(i.verdictWord).toBe("one model");
    expect(i.facts?.[0]).toBe("Dearest session: Dear at $9.00 over 42 turns.");
    expect(i.facts?.[1]).toMatch(/^7 turns ran on models the price table does not know/);
    expect(i.resolutions).toHaveLength(1);
  });

  it("has no data with none priced", () => {
    expect(costPerTurnByModel(inputs({ models: [model({ model: "a", cost_usd: null })] })).verdict).toBe("none");
    expect(costPerTurnByModel(inputs()).verdict).toBe("none");
  });
});

describe("costPerPrompt", () => {
  it("prices a prompt and a session, as information not a verdict", () => {
    const i = costPerPrompt(
      inputs({
        totals: totals({ cost_usd: 25, prompts: 10, sessions: 2, turns: 100 }),
        shape: {
          turns: { p50: 1, p90: 1, max: 1, mean: 1 },
          prompts: { p50: 1, p90: 1, max: 1, mean: 1 },
          duration_s: { p50: 1, p90: 1, max: 1, mean: 1 },
          transcript_bytes: { p50: 1, p90: 1, max: 1, mean: 1 },
          peak_context_tokens: { p50: 1, p90: 1, max: 1, mean: 1 },
          cost_usd: { p50: 4, p90: 20, max: 21, mean: 12.5 },
        },
      })
    );
    expect(i.value).toBe("$2.50");
    expect(i.verdict).toBe("info");
    expect(i.counsel).toMatch(/ran 10 turns/);
    expect(i.detail).toBe("$12.50 per session · $25.00 in all");
    expect(i.facts?.[0]).toBe("Median session $4.00; the dearest $21.00.");
    expect(i.facts?.[1]).toBe("About 5 prompts per session across 2 sessions.");
    expect(i.resolutions?.map((r) => r.title)).toEqual(["Bundle related asks into one prompt"]);
  });

  it("has no data without priced prompts", () => {
    expect(costPerPrompt(inputs({ totals: totals({ cost_usd: 0 }) })).verdict).toBe("none");
    expect(costPerPrompt(inputs({ totals: totals({ prompts: 0, cost_usd: 5 }) })).verdict).toBe("none");
  });
});

describe("thinkingShare", () => {
  it("bands the thinking share of output and scales the levers", () => {
    const light = thinkingShare(inputs({ totals: totals({ output_tokens: 100, thinking_tokens: 10 }) }));
    expect(light.verdictWord).toBe("light");
    expect(light.resolutions).toHaveLength(1);
    expect(thinkingShare(inputs({ totals: totals({ output_tokens: 100, thinking_tokens: 30 }) })).verdictWord).toBe("balanced");
    const deep = thinkingShare(inputs({ totals: totals({ output_tokens: 100, thinking_tokens: 60 }) }));
    expect(deep.value).toBe("60%");
    expect(deep.verdict).toBe("poor");
    expect(deep.detail).toMatch(/billed at output rates/);
    expect(deep.resolutions?.map((r) => r.title)).toContain("Drop effort for the simple stuff");
    expect(deep.resolutions).toHaveLength(3);
  });

  it("names the sessions that thought hardest", () => {
    const i = thinkingShare(
      inputs({
        sessions: [
          session({ session_id: "a", title: "Ponder", output_tokens: 100, thinking_tokens: 70 }),
          session({ session_id: "b", output_tokens: 100, thinking_tokens: 5 }),
        ],
      })
    );
    expect(i.facts).toEqual(["1 of 2 sessions spent more than half their output thinking.", "Deepest: Ponder at 70%."]);
  });

  it("has nothing to say without output", () => {
    expect(thinkingShare(inputs({ totals: totals({ output_tokens: 0 }) })).verdict).toBe("none");
  });
});

describe("windowInsights", () => {
  it("returns the page's counsel in display order, each with its levers", () => {
    const all = windowInsights(inputs());
    expect(all.map((i) => i.id)).toEqual([
      "window-fill", "cost-per-turn", "cost-per-prompt", "thinking-share",
      "rework-share", "delegation-balance",
    ]);
    // Every banded insight offers levers; only the no-data model row goes without.
    expect(all.filter((i) => i.verdict !== "none").every((i) => (i.resolutions?.length ?? 0) > 0)).toBe(true);
  });
});

describe("reworkShare", () => {
  const churn = (added: number, removed: number, over = { files: 10, edits: 40, sessions: 5 }) => ({
    lines_added: added, lines_removed: removed, files: over.files, edits: over.edits,
    files_by_churn: [], sessions: over.sessions, output_tokens: 0, by_day: [],
  });

  it("reads a low removed/added ratio as building", () => {
    const i = reworkShare({ churn: churn(1000, 50) });
    expect(i.verdict).toBe("good");
    expect(i.value).toBe("5%");
  });

  it("reads a high ratio as rewriting", () => {
    const i = reworkShare({ churn: churn(1000, 700) });
    expect(i.verdict).toBe("poor");
    expect(i.verdictWord).toBe("rewriting");
  });

  it("has no reading without churn data", () => {
    expect(reworkShare({ churn: undefined }).verdict).toBe("none");
    expect(reworkShare({ churn: churn(0, 0) }).verdict).toBe("none");
  });

  it("names the files that absorbed the most rework", () => {
    const i = reworkShare({
      churn: {
        ...churn(1000, 400),
        files_by_churn: [
          { file_path: "/r/styles.css", edits: 472, lines_added: 500, lines_removed: 300,
            operations: ["edit"], sessions: 9 },
        ],
      },
    });
    expect(i.facts?.join(" ")).toMatch(/styles\.css/);
  });
});

describe("delegationBalance", () => {
  const d = (turnPct: number, outPct: number) => ({
    turns: 1000, subagent_turns: turnPct * 10,
    output_tokens: 1000, subagent_output_tokens: outPct * 10,
    tool_calls: 1000, subagent_tool_calls: turnPct * 10,
  });

  it("names the gap between turns delegated and output produced", () => {
    const i = delegationBalance({ delegation: d(60, 13) });
    expect(i.value).toBe("60%");
    expect(i.detail).toMatch(/13%/);
  });

  it("reads heavy delegation with little output as reading work", () => {
    expect(delegationBalance({ delegation: d(60, 13) }).verdictWord).toMatch(/read|search|gather/i);
  });

  it("has no reading with no turns", () => {
    expect(delegationBalance({ delegation: undefined }).verdict).toBe("none");
  });
});
