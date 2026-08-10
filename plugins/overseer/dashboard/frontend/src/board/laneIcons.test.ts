import { describe, expect, it } from "vitest";
import type { Lane } from "./layout";
import { laneIcon, laneIconKey } from "./laneIcons";

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
});
