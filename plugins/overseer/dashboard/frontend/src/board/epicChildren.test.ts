import { describe, expect, it } from "vitest";
import { groupChildrenByEpic } from "./epicChildren";
import type { BoardCard } from "../api/types";

function card(id: string, parent: string | null = null): BoardCard {
  return {
    id, title: id, status: "planned", stage: null, complexity: null, priority: null,
    sprint: null, parent, depends_on: [], order: 1, budget: { estimate: null, actual: 0 },
    is_epic: false, ready: true, rollup: null, created: "", updated: "", labels: [],
    links: [], body: "", checklist: [], pr: null, claimed_by: null,
  } as BoardCard;
}

describe("groupChildrenByEpic", () => {
  it("groups children under their parent id", () => {
    const m = groupChildrenByEpic([card("E1"), card("A", "E1"), card("B", "E1"), card("C")]);
    expect(m.get("E1")?.map((c) => c.id)).toEqual(["A", "B"]);
  });
  it("omits parents with no children", () => {
    const m = groupChildrenByEpic([card("E1"), card("E2")]);
    expect(m.has("E1")).toBe(false);
    expect(m.size).toBe(0);
  });
  it("preserves input order within a parent", () => {
    const m = groupChildrenByEpic([card("B", "E1"), card("A", "E1")]);
    expect(m.get("E1")?.map((c) => c.id)).toEqual(["B", "A"]);
  });
});
