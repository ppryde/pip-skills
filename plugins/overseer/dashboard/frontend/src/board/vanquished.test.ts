import { describe, expect, it } from "vitest";
import { vanquishedStats } from "./vanquished";
import type { BoardCard, Status } from "../api/types";

function card(status: Status): BoardCard {
  return {
    id: "WF-X",
    title: "x",
    status,
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
    checklist: [],
  };
}

describe("vanquishedStats", () => {
  it("returns 0/0 for no cards", () => {
    expect(vanquishedStats([])).toEqual({ done: 0, total: 0 });
  });

  it("counts done cards against the total card count", () => {
    const cards = [
      card("done"),
      card("done"),
      card("in-flight"),
      card("planned"),
      card("parked"),
    ];
    expect(vanquishedStats(cards)).toEqual({ done: 2, total: 5 });
  });

  it("counts every status other than done as not vanquished, including abandoned", () => {
    expect(vanquishedStats([card("abandoned"), card("blocked")])).toEqual({
      done: 0,
      total: 2,
    });
  });
});
