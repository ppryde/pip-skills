import { describe, expect, it } from "vitest";
import { cardIconKey, iconKeyLabel } from "./laneIcons";
import type { BoardCard, Stage, Status } from "../api/types";

function card(status: Status, stage: Stage | null = null): BoardCard {
  return {
    id: "WF-X", title: "x", status, stage, complexity: null, priority: null,
    sprint: null, parent: null, depends_on: [], order: 10,
    budget: { estimate: null, actual: 0 }, is_epic: false, ready: true,
    rollup: null, created: "", updated: "", labels: [], links: [],
    body: "", checklist: [], pr: null,
    claimed_by: null,
  } as BoardCard;
}

describe("cardIconKey", () => {
  it("planned -> backlog", () => expect(cardIconKey(card("planned"))).toBe("backlog"));
  it("blocked with no stage -> backlog", () =>
    expect(cardIconKey(card("blocked", null))).toBe("backlog"));
  it("in-flight with a stage -> that stage", () =>
    expect(cardIconKey(card("in-flight", "impl-review"))).toBe("impl-review"));
  it("blocked with a stage -> that stage", () =>
    expect(cardIconKey(card("blocked", "implementation"))).toBe("implementation"));
  it("parked -> parked", () => expect(cardIconKey(card("parked"))).toBe("parked"));
  it("done -> done", () => expect(cardIconKey(card("done"))).toBe("done"));
  it("abandoned -> abandoned", () => expect(cardIconKey(card("abandoned"))).toBe("abandoned"));
  it("done ignores a lingering stage -> done", () =>
    expect(cardIconKey(card("done", "verification"))).toBe("done"));
});

describe("iconKeyLabel", () => {
  it("labels a stage key", () => expect(iconKeyLabel("impl-review")).toBe("Impl Review"));
  it("labels a bucket key", () => expect(iconKeyLabel("backlog")).toBe("Backlog"));
  it("labels every icon key non-empty", () => {
    for (const k of ["backlog","bootstrap","planning","plan-review","implementation",
      "impl-review","verification","awaiting-merge","done","parked","abandoned","in-progress"])
      expect(iconKeyLabel(k).length).toBeGreaterThan(0);
  });
});
