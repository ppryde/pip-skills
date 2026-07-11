import { describe, expect, it } from "vitest";
import { orderForDrop } from "./order";
import type { BoardCard } from "../api/types";

/** Minimal card builder — only `order`/`id` matter for these tests. */
function card(id: string, order: number): BoardCard {
  return {
    id,
    title: `Title ${id}`,
    status: "planned",
    stage: null,
    complexity: null,
    priority: null,
    sprint: null,
    parent: null,
    depends_on: [],
    order,
    budget: { estimate: null, actual: 0 },
    is_epic: false,
    ready: true,
    rollup: null,
  };
}

describe("orderForDrop", () => {
  it("returns a sensible base order for an empty lane", () => {
    expect(orderForDrop([], 0)).toBe(0);
  });

  it("drops before the sole neighbour at lane start: below.order - 10", () => {
    const lane = [card("A", 10)];
    expect(orderForDrop(lane, 0)).toBe(0); // 10 - 10
  });

  it("drops after the sole neighbour at lane end: above.order + 10", () => {
    const lane = [card("A", 10)];
    expect(orderForDrop(lane, 1)).toBe(20); // 10 + 10
  });

  it("drops at the interior midpoint of two neighbours", () => {
    const lane = [card("A", 10), card("B", 30)];
    expect(orderForDrop(lane, 1)).toBe(20); // floor((10+30)/2)
  });

  it("tolerates a tie when the midpoint collides with a neighbour's order (documented known limitation)", () => {
    // Adjacent neighbours packed tight (10, 11): floor((10+11)/2) === 10,
    // which COLLIDES with the "above" neighbour's own order. This is a
    // known, tolerated limitation — layout.ts's lane sort tiebreaks on `id`
    // so a colliding order still yields a stable (if not perfectly ordered)
    // render; there is no client-side renumbering pass.
    const lane = [card("A", 10), card("B", 11)];
    expect(orderForDrop(lane, 1)).toBe(10);
  });

  it("multiple boundary drops at the start and end of a larger lane", () => {
    const lane = [card("A", 10), card("B", 20), card("C", 30)];
    expect(orderForDrop(lane, 0)).toBe(0); // before A: 10 - 10
    expect(orderForDrop(lane, 3)).toBe(40); // after C: 30 + 10
  });
});
