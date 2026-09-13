import { describe, expect, it } from "vitest";
import type { AlmonerItem } from "../../api/types";
import { LANES, dayBand } from "./band";

function item(over: Partial<AlmonerItem> = {}): AlmonerItem {
  return { id: "i1", source: "slack", context: "work", title: "DM", ...over };
}

const local = (hhmm: string) => `2026-09-13T${hhmm}:00`;

describe("dayBand", () => {
  it("returns nothing when no item can be placed in time", () => {
    // The band is a picture of when things arrived; with no times there is
    // no picture, and an empty axis is worse than no axis.
    expect(dayBand([])).toBeNull();
    expect(dayBand([item({ asks: "reconcile" })])).toBeNull();
  });

  it("spans the day's first arrival to its last, snapped to whole hours", () => {
    const band = dayBand([
      item({ id: "a", arrived: local("09:20") }),
      item({ id: "b", arrived: local("17:40") }),
    ]);
    expect(new Date(band!.startMs).getHours()).toBe(9);
    expect(new Date(band!.endMs).getHours()).toBe(18);
  });

  it("widens a narrow day to a readable minimum span", () => {
    // Two messages ten minutes apart must not produce an axis where the
    // whole day is one pixel of crowding.
    const band = dayBand([
      item({ id: "a", arrived: local("14:00") }),
      item({ id: "b", arrived: local("14:10") }),
    ]);
    expect(band!.endMs - band!.startMs).toBeGreaterThanOrEqual(4 * 3600_000);
  });

  it("starts at the earliest arrival and leaves the last one room to breathe", () => {
    // The window runs to the END of the last arrival's hour, so the final
    // blip sits inside the axis rather than half-clipped on its right edge.
    const band = dayBand([
      item({ id: "a", arrived: local("09:00") }),
      item({ id: "b", arrived: local("17:00") }),
    ]);
    const last = band!.blips[band!.blips.length - 1];
    expect(band!.blips[0].leftPct).toBe(0);
    expect(last.leftPct).toBeGreaterThan(50);
    expect(last.leftPct).toBeLessThan(100);
  });

  it("keeps every blip inside the drawing", () => {
    const band = dayBand([
      item({ id: "a", arrived: local("09:00") }),
      item({ id: "b", arrived: local("12:30") }),
      item({ id: "c", arrived: local("17:00") }),
    ]);
    for (const blip of band!.blips) {
      expect(blip.leftPct).toBeGreaterThanOrEqual(0);
      expect(blip.leftPct).toBeLessThanOrEqual(100);
    }
  });

  it("lifts clustered arrivals into different lanes so they do not overlap", () => {
    // The 19:06 pile-up is the whole point of the picture; three dots drawn
    // on top of each other would hide exactly what it exists to show.
    const band = dayBand([
      item({ id: "a", arrived: local("19:06") }),
      item({ id: "b", arrived: local("19:07") }),
      item({ id: "c", arrived: local("19:08") }),
      item({ id: "d", arrived: local("09:00") }),
    ]);
    const lanes = band!.blips.map((b) => b.lane);
    expect(new Set(lanes.slice(1)).size).toBeGreaterThan(1);
  });

  it("drops a lone arrival back to the baseline lane", () => {
    const band = dayBand([
      item({ id: "a", arrived: local("09:00") }),
      item({ id: "b", arrived: local("17:00") }),
    ]);
    expect(band!.blips[0].lane).toBe(0);
    expect(band!.blips[1].lane).toBe(0);
  });

  it("never exceeds the lane count it promises", () => {
    const band = dayBand(
      Array.from({ length: 12 }, (_, i) =>
        item({ id: `i${i}`, arrived: `2026-09-13T14:0${i % 10}:00` })
      )
    );
    for (const blip of band!.blips) {
      expect(blip.lane).toBeLessThan(LANES);
    }
  });

  it("carries the source and whether it still wants you", () => {
    const band = dayBand([
      item({ id: "a", source: "linear", arrived: local("09:00"), awaiting: true }),
      item({ id: "b", arrived: local("17:00"), awaiting: false }),
    ]);
    expect(band!.blips[0]).toMatchObject({ id: "a", source: "linear", open: true });
    expect(band!.blips[1].open).toBe(false);
  });

  it("puts an hour tick inside the window for each hour it spans", () => {
    const band = dayBand([
      item({ id: "a", arrived: local("09:00") }),
      item({ id: "b", arrived: local("13:00") }),
    ]);
    expect(band!.hours.length).toBeGreaterThan(1);
    for (const hour of band!.hours) {
      expect(hour.leftPct).toBeGreaterThanOrEqual(0);
      expect(hour.leftPct).toBeLessThanOrEqual(100);
    }
  });

  it("ignores an unparseable arrival rather than placing it at the epoch", () => {
    const band = dayBand([
      item({ id: "good", arrived: local("09:00") }),
      item({ id: "bad", arrived: "not a date" }),
      item({ id: "also", arrived: local("17:00") }),
    ]);
    expect(band!.blips.map((b) => b.id)).toEqual(["good", "also"]);
  });
});

describe("dayBand — rollups", () => {
  it("leaves rollups off the band", () => {
    // A row standing for four newsletters would plot as one dot of equal
    // weight to a review request. The band shows when WORK reached you.
    const band = dayBand([
      item({ id: "real", arrived: local("09:00") }),
      item({ id: "rollup", arrived: local("11:00"), bundled: true }),
      item({ id: "also", arrived: local("17:00") }),
    ]);
    expect(band!.blips.map((b) => b.id)).toEqual(["real", "also"]);
  });

  it("returns no band for a day of nothing but rollups", () => {
    expect(dayBand([item({ arrived: local("09:00"), bundled: true })])).toBeNull();
  });
});
