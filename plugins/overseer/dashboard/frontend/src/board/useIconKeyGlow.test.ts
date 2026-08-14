import { describe, expect, it } from "vitest";
import { changedIconKeys } from "./useIconKeyGlow";

describe("changedIconKeys", () => {
  it("reports ids whose key changed", () => {
    const prev = new Map([["a", "planning"], ["b", "done"]]);
    const next = new Map([["a", "implementation"], ["b", "done"]]);
    expect(changedIconKeys(prev, next)).toEqual(["a"]);
  });
  it("a newly-seen id is not a change (no prior key)", () => {
    expect(changedIconKeys(new Map(), new Map([["a", "done"]]))).toEqual([]);
  });
  it("no change -> empty", () => {
    const m = new Map([["a", "done"]]);
    expect(changedIconKeys(m, new Map([["a", "done"]]))).toEqual([]);
  });
});
