import { describe, expect, it } from "vitest";
import type { AlmonerItem } from "../../api/types";
import { clockTime, groupByDay } from "./days";

const NOW = Date.parse("2026-09-13T12:00:00Z");

function item(over: Partial<AlmonerItem> = {}): AlmonerItem {
  return { id: "i1", source: "slack", context: "work", title: "DM", ...over };
}

describe("groupByDay", () => {
  it("labels the current day Today", () => {
    const [day] = groupByDay([item({ arrived: "2026-09-13T09:00:00Z" })], NOW);
    expect(day.label).toMatch(/^Today/);
  });

  it("labels the previous day Yesterday", () => {
    const [day] = groupByDay([item({ arrived: "2026-09-12T09:00:00Z" })], NOW);
    expect(day.label).toMatch(/^Yesterday/);
  });

  it("names older days outright rather than counting backwards", () => {
    // "4 days ago" makes the reader do arithmetic to place a meeting.
    const [day] = groupByDay([item({ arrived: "2026-09-09T09:00:00Z" })], NOW);
    expect(day.label).not.toMatch(/Today|Yesterday/);
    expect(day.label).toMatch(/September/);
  });

  it("puts the most recent day first", () => {
    const days = groupByDay(
      [
        item({ id: "old", arrived: "2026-09-11T09:00:00Z" }),
        item({ id: "new", arrived: "2026-09-13T09:00:00Z" }),
      ],
      NOW
    );
    expect(days[0].label).toMatch(/^Today/);
  });

  it("orders items newest-first inside a day", () => {
    const [day] = groupByDay(
      [
        item({ id: "early", arrived: "2026-09-13T09:00:00Z" }),
        item({ id: "late", arrived: "2026-09-13T11:00:00Z" }),
      ],
      NOW
    );
    expect(day.items.map((i) => i.id)).toEqual(["late", "early"]);
  });

  it("puts undated items at the top of the newest day", () => {
    // Derived reconcile checks have no arrival time but are current — an
    // orphan "no date" group would read as an error rather than a finding.
    const days = groupByDay(
      [
        item({ id: "dated", arrived: "2026-09-13T09:00:00Z" }),
        item({ id: "derived", asks: "reconcile" }),
      ],
      NOW
    );
    expect(days).toHaveLength(1);
    expect(days[0].items.map((i) => i.id)).toEqual(["derived", "dated"]);
  });

  it("still groups when every item is undated", () => {
    const days = groupByDay([item({ id: "d", asks: "reconcile" })], NOW);
    expect(days).toHaveLength(1);
    expect(days[0].label).toMatch(/^Today/);
  });

  it("treats an unparseable arrival time as undated rather than crashing", () => {
    const days = groupByDay([item({ id: "bad", arrived: "not a date" })], NOW);
    expect(days[0].items.map((i) => i.id)).toEqual(["bad"]);
  });

  it("returns nothing for an empty digest", () => {
    expect(groupByDay([], NOW)).toEqual([]);
  });
});

describe("clockTime", () => {
  it("renders the wall-clock time of an arrival", () => {
    expect(clockTime("2026-09-13T19:06:00")).toBe("19:06");
  });

  it("pads a single-digit hour and minute", () => {
    expect(clockTime("2026-09-13T09:05:00")).toBe("09:05");
  });

  it("renders nothing for an absent or unparseable time", () => {
    expect(clockTime(undefined)).toBe("");
    expect(clockTime("not a date")).toBe("");
  });
});
