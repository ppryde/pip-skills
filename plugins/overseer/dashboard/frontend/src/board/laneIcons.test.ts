import { describe, expect, it } from "vitest";
import type { Lane } from "./layout";
import { cardIconKey, iconKeyLabel, laneIcon, laneIconKey, stageIcon } from "./laneIcons";
import type { BoardCard, Stage, Status } from "../api/types";

function lane(overrides: Partial<Lane> & Pick<Lane, "key" | "kind">): Lane {
  return { label: "", cards: [], ...overrides };
}

describe("laneIconKey", () => {
  it("maps backlog/parked/done lanes to their own kind", () => {
    expect(laneIconKey(lane({ key: "backlog", kind: "backlog" }))).toBe("backlog");
    expect(laneIconKey(lane({ key: "parked", kind: "parked" }))).toBe("parked");
    expect(laneIconKey(lane({ key: "done", kind: "done" }))).toBe("done");
  });

  it("maps the archive lane (labelled Abandoned) to 'abandoned'", () => {
    expect(laneIconKey(lane({ key: "archive", kind: "archive" }))).toBe("abandoned");
  });

  it("maps the mobile in-progress lane (WF-085 collapseStagesForMobile) to 'in-progress'", () => {
    expect(
      laneIconKey(lane({ key: "in-progress", kind: "in-progress" }))
    ).toBe("in-progress");
  });

  it("maps every stage lane to its own stage string", () => {
    const stages = [
      "bootstrap",
      "planning",
      "plan-review",
      "implementation",
      "impl-review",
      "verification",
      "awaiting-merge",
    ] as const;
    stages.forEach((stage) => {
      expect(
        laneIconKey(lane({ key: `stage:${stage}`, kind: "stage", stage }))
      ).toBe(stage);
    });
  });
});

describe("laneIcon", () => {
  it("returns a bundled URL for all 11 icon keys", () => {
    const keys = [
      "backlog",
      "bootstrap",
      "planning",
      "plan-review",
      "implementation",
      "impl-review",
      "verification",
      "awaiting-merge",
      "done",
      "parked",
      "abandoned",
    ];
    keys.forEach((key) => {
      expect(laneIcon(key)).toEqual(expect.any(String));
      expect(laneIcon(key).length).toBeGreaterThan(0);
    });
    // Every key resolves to a distinct asset.
    expect(new Set(keys.map(laneIcon)).size).toBe(keys.length);
  });

  it("falls back to the backlog icon for an unrecognised key", () => {
    expect(laneIcon("not-a-real-lane")).toBe(laneIcon("backlog"));
  });

  it("resolves 'in-progress' to its own bundled asset, distinct from every stage icon", () => {
    expect(laneIcon("in-progress")).toEqual(expect.any(String));
    expect(laneIcon("in-progress")).not.toBe(laneIcon("backlog"));
    expect(laneIcon("in-progress")).not.toBe(laneIcon("implementation"));
  });
});

describe("stageIcon", () => {
  it("resolves a stage to the SAME icon its stage:<S> lane would use", () => {
    const stages = [
      "bootstrap",
      "planning",
      "plan-review",
      "implementation",
      "impl-review",
      "verification",
      "awaiting-merge",
    ] as const;
    stages.forEach((stage) => {
      expect(stageIcon(stage)).toBe(laneIcon(stage));
    });
  });
});

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
