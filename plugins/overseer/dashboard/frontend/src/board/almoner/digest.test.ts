import { describe, expect, it } from "vitest";
import type { AlmonerItem, AlmonerSource } from "../../api/types";
import { failedSources, groupDigest, relativeArrived, rowState } from "./digest";

function item(over: Partial<AlmonerItem> = {}): AlmonerItem {
  return { id: "slack:C1", source: "slack", context: "work", title: "DM · Rhona", ...over };
}

describe("groupDigest", () => {
  it("puts an item whose last message is not yours in Awaiting", () => {
    const [group] = groupDigest([item({ awaiting: true })]);
    expect(group.key).toBe("awaiting");
    expect(group.items).toHaveLength(1);
  });

  it("puts an item you answered last in FYI, not Awaiting", () => {
    // The 11:06 "can I put in some time today?" that was settled by 13:37:
    // a digest that still calls that an open ask is simply wrong.
    const [group] = groupDigest([item({ awaiting: false })]);
    expect(group.key).toBe("fyi");
  });

  it("treats a missing `awaiting` as not awaiting", () => {
    // A source whose adapter cannot compute the rule must not manufacture
    // urgency by omission.
    const [group] = groupDigest([item({})]);
    expect(group.key).toBe("fyi");
  });

  it("gives derived reconcile items their own group even when awaiting", () => {
    // Nobody sent these and they have no arrival time; they must not compete
    // with things a person actually said to you.
    const groups = groupDigest([
      item({ id: "x", asks: "reconcile", awaiting: true }),
      item({ id: "y", awaiting: true }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["awaiting", "reconcile"]);
    expect(groups[1].items.map((i) => i.id)).toEqual(["x"]);
  });

  it("omits groups that have no items", () => {
    expect(groupDigest([item({ awaiting: true })]).map((g) => g.key)).toEqual(["awaiting"]);
  });

  it("returns no groups for an empty digest", () => {
    expect(groupDigest([])).toEqual([]);
  });

  it("orders a judged group by rank ascending", () => {
    const groups = groupDigest([
      item({ id: "b", awaiting: true, rank: 2 }),
      item({ id: "a", awaiting: true, rank: 1 }),
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("falls back to newest-first when the judging pass did not run", () => {
    const groups = groupDigest([
      item({ id: "old", awaiting: true, arrived: "2026-09-11T09:00:00Z" }),
      item({ id: "new", awaiting: true, arrived: "2026-09-11T19:06:15Z" }),
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["new", "old"]);
  });

  it("sorts ranked items above unranked ones in the same group", () => {
    const groups = groupDigest([
      item({ id: "unranked", awaiting: true, arrived: "2026-09-12T09:00:00Z" }),
      item({ id: "ranked", awaiting: true, rank: 9, arrived: "2026-09-01T09:00:00Z" }),
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["ranked", "unranked"]);
  });

  it("keeps an item with no arrival time without throwing", () => {
    const groups = groupDigest([
      item({ id: "dated", awaiting: true, arrived: "2026-09-11T09:00:00Z" }),
      item({ id: "undated", awaiting: true }),
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["dated", "undated"]);
  });

  it("ignores an unparseable arrival time rather than reordering on NaN", () => {
    const groups = groupDigest([
      item({ id: "good", awaiting: true, arrived: "2026-09-11T09:00:00Z" }),
      item({ id: "bad", awaiting: true, arrived: "not a date" }),
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["good", "bad"]);
  });
});

describe("failedSources", () => {
  const src = (over: Partial<AlmonerSource>): AlmonerSource => ({
    label: "slack", type: "slack", ok: true, ...over,
  });

  it("names the sources that did not answer", () => {
    expect(failedSources([src({ label: "linear", ok: false }), src({})])).toEqual(["linear"]);
  });

  it("returns nothing when every source answered", () => {
    expect(failedSources([src({}), src({ label: "linear" })])).toEqual([]);
  });

  it("treats an absent source list as nothing failed", () => {
    expect(failedSources(undefined)).toEqual([]);
  });
});

describe("relativeArrived", () => {
  const now = Date.parse("2026-09-13T12:00:00Z");

  it("renders minutes, hours and days", () => {
    expect(relativeArrived("2026-09-13T11:30:00Z", now)).toBe("30m");
    expect(relativeArrived("2026-09-13T09:00:00Z", now)).toBe("3h");
    expect(relativeArrived("2026-09-11T12:00:00Z", now)).toBe("2d");
  });

  it("collapses the last minute to 'now'", () => {
    expect(relativeArrived("2026-09-13T11:59:30Z", now)).toBe("now");
  });

  it("clamps a future timestamp to 'now' rather than going negative", () => {
    // Clock skew between providers is real and the design allows for it.
    expect(relativeArrived("2026-09-13T12:05:00Z", now)).toBe("now");
  });

  it("renders nothing for an absent or unparseable time", () => {
    // Derived reconcile items have no arrival time at all.
    expect(relativeArrived(undefined, now)).toBe("");
    expect(relativeArrived("not a date", now)).toBe("");
  });
});

describe("rowState", () => {
  it("calls an item awaiting you 'needs you'", () => {
    expect(rowState(item({ awaiting: true }))).toEqual({ key: "open", label: "needs you" });
  });

  it("calls a derived check 'reconcile', even when it is awaiting", () => {
    expect(rowState(item({ asks: "reconcile", awaiting: true })).key).toBe("reconcile");
  });

  it("calls anything else settled", () => {
    expect(rowState(item({ awaiting: false })).key).toBe("settled");
    expect(rowState(item({})).key).toBe("settled");
  });

  it("agrees with groupDigest about what every row is", () => {
    // The table and the grouped view may disagree about where a row sits,
    // never about what it is.
    const items = [
      item({ id: "a", awaiting: true }),
      item({ id: "b", asks: "reconcile" }),
      item({ id: "c", awaiting: false }),
    ];
    const groupOf: Record<string, string> = { awaiting: "open", reconcile: "reconcile", fyi: "settled" };
    for (const group of groupDigest(items)) {
      for (const each of group.items) {
        expect(rowState(each).key).toBe(groupOf[group.key]);
      }
    }
  });
});

describe("rowState — rollups", () => {
  it("calls a folded batch of machine mail bundled", () => {
    expect(rowState(item({ bundled: true }))).toEqual({ key: "bundled", label: "bundled" });
  });

  it("never lets a rollup claim to need you", () => {
    // Whatever an adapter set on `awaiting`, nobody is waiting on a reply to
    // four newsletters.
    expect(rowState(item({ bundled: true, awaiting: true })).key).toBe("bundled");
  });

  it("still lets a derived check outrank a rollup", () => {
    expect(rowState(item({ bundled: true, asks: "reconcile" })).key).toBe("reconcile");
  });
});
