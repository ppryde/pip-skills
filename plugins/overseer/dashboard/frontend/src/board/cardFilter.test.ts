import { it, expect } from "vitest";
import { visibleCardIds, distinctLabels, DEFAULT_FILTER } from "./cardFilter";
import type { FilterState } from "./cardFilter";
import type { BoardCard } from "../api/types";

const card = (o: Partial<BoardCard> & { id: string }): BoardCard => ({
  id: o.id, title: o.title ?? o.id, body: o.body ?? "", status: "planned",
  stage: null, complexity: o.complexity ?? null, priority: o.priority ?? null,
  sprint: null, parent: o.parent ?? null, depends_on: [], order: 0,
  budget: { estimate: null, actual: 0 }, is_epic: false, ready: true,
  rollup: null, created: "", updated: "", checklist: [], labels: o.labels ?? [],
});
const ids = (cards: BoardCard[], s: FilterState) => [...visibleCardIds(cards, s)].sort();
const F = (o: Partial<FilterState>): FilterState => ({ ...DEFAULT_FILTER, excludeLabels: [], ...o });

it("empty filter shows everything", () => {
  const cs = [card({ id: "A" }), card({ id: "B" })];
  expect(ids(cs, F({}))).toEqual(["A", "B"]);
});
it("search matches id/title/body, case-insensitive", () => {
  const cs = [card({ id: "A", title: "Frobnicate" }), card({ id: "B", body: "see the FROB" }), card({ id: "C", title: "nope" })];
  expect(ids(cs, F({ query: "frob" }))).toEqual(["A", "B"]);
});
it("exclude wins over include", () => {
  const cs = [card({ id: "A", labels: ["x", "y"] })];
  expect(ids(cs, F({ includeLabels: ["x"], excludeLabels: ["y"] }))).toEqual([]);
});
it("include is an OR across active labels", () => {
  const cs = [card({ id: "A", labels: ["x"] }), card({ id: "B", labels: ["z"] }), card({ id: "C", labels: ["y"] })];
  expect(ids(cs, F({ includeLabels: ["x", "y"] }))).toEqual(["A", "C"]);
});
it("priority + complexity are strict equality when set", () => {
  const cs = [card({ id: "A", priority: "P0", complexity: "L" }), card({ id: "B", priority: "P1", complexity: "L" })];
  expect(ids(cs, F({ priority: "P0" }))).toEqual(["A"]);
  expect(ids(cs, F({ complexity: "L" }))).toEqual(["A", "B"]);
});
it("a search-matched epic reveals ALL its children, bypassing an active label filter", () => {
  const cs = [
    card({ id: "EPIC", title: "Migration epic" }),
    card({ id: "K1", parent: "EPIC", labels: ["future"] }),
    card({ id: "K2", parent: "EPIC", labels: ["ui"] }),
    card({ id: "OTHER", title: "unrelated" }),
  ];
  // exclude future is active, but EPIC matches → its children (incl. future one) all show
  expect(ids(cs, F({ query: "migration", excludeLabels: ["future"] }))).toEqual(["EPIC", "K1", "K2"]);
});
it("a non-parent direct match still must pass the active filters", () => {
  const cs = [card({ id: "A", title: "frob", labels: ["future"] })];
  expect(ids(cs, F({ query: "frob", excludeLabels: ["future"] }))).toEqual([]); // gated out
  expect(ids(cs, F({ query: "frob" }))).toEqual(["A"]); // no exclude → shows
});
it("default filter hides `future` cards", () => {
  const cs = [card({ id: "A", labels: ["future"] }), card({ id: "B" })];
  expect(ids(cs, DEFAULT_FILTER)).toEqual(["B"]);
});
it("distinctLabels is sorted + unique", () => {
  expect(distinctLabels([card({ id: "A", labels: ["z", "a"] }), card({ id: "B", labels: ["a", "m"] })])).toEqual(["a", "m", "z"]);
});
