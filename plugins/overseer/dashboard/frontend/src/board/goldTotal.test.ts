import { describe, expect, it } from "vitest";
import { goldTotal } from "./goldTotal";
import type { BoardCard } from "../api/types";

function card(actual: number): BoardCard {
  return {
    id: "WF-X",
    title: "x",
    status: "planned",
    stage: null,
    complexity: null,
    priority: null,
    sprint: null,
    parent: null,
    depends_on: [],
    order: 10,
    budget: { estimate: null, actual },
    is_epic: false,
    ready: true,
    rollup: null,
    checklist: [],
  };
}

describe("goldTotal", () => {
  it("returns 0 for no cards", () => {
    expect(goldTotal([])).toBe(0);
  });

  it("sums budget.actual across all cards", () => {
    expect(goldTotal([card(100), card(250), card(0)])).toBe(350);
  });

  it("ignores estimate — only actual counts as spent gold", () => {
    const c = card(500);
    c.budget.estimate = 999999;
    expect(goldTotal([c])).toBe(500);
  });
});
