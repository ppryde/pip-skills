import { describe, expect, it } from "vitest";
import { distinctBranches } from "./branches";
import type { BoardCard, SessionSummary } from "../api/types";

function card(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    title: `Title ${overrides.id}`,
    status: "planned",
    stage: null,
    complexity: null,
    priority: null,
    sprint: null,
    parent: null,
    depends_on: [],
    order: 10,
    budget: { estimate: null, actual: 0 },
    is_epic: false,
    ready: true,
    rollup: null,
    created: "",
    updated: "",
    checklist: [],
    labels: [],
    body: "",
    ...overrides,
  };
}

function session(overrides: Partial<SessionSummary> & { id: string }): SessionSummary {
  return {
    worktree_cwd: "/w",
    updated_at: 100,
    stale: false,
    ...overrides,
  };
}

describe("distinctBranches", () => {
  it("unions branch names across cards and sessions", () => {
    const cards = [card({ id: "WF-1", branch: "feat/a" })];
    const sessions = [session({ id: "s1", branch: "feat/b" })];

    expect(distinctBranches(cards, sessions)).toEqual(["feat/a", "feat/b"]);
  });

  it("dedupes a branch shared by a card and a session", () => {
    const cards = [card({ id: "WF-1", branch: "feat/shared" })];
    const sessions = [session({ id: "s1", branch: "feat/shared" })];

    expect(distinctBranches(cards, sessions)).toEqual(["feat/shared"]);
  });

  it("drops undefined/empty branches from both cards and sessions", () => {
    const cards = [
      card({ id: "WF-1", branch: undefined }),
      card({ id: "WF-2", branch: "" }),
      card({ id: "WF-3", branch: "feat/kept" }),
    ];
    const sessions = [
      session({ id: "s1", branch: undefined }),
      session({ id: "s2", branch: "" }),
    ];

    expect(distinctBranches(cards, sessions)).toEqual(["feat/kept"]);
  });

  it("sorts the result", () => {
    const cards = [
      card({ id: "WF-1", branch: "zeta" }),
      card({ id: "WF-2", branch: "alpha" }),
      card({ id: "WF-3", branch: "mid" }),
    ];

    expect(distinctBranches(cards, [])).toEqual(["alpha", "mid", "zeta"]);
  });

  it("returns an empty array when nothing carries a branch", () => {
    expect(distinctBranches([card({ id: "WF-1" })], [session({ id: "s1" })])).toEqual([]);
  });

  it("returns an empty array for empty inputs", () => {
    expect(distinctBranches([], [])).toEqual([]);
  });
});
