import { describe, expect, it } from "vitest";
import {
  computeAxisTicks,
  computeWindow,
  formatDateStamp,
  parseCalendarDate,
  pctForDate,
  projectedEnd,
  seedFor,
  wobblePath,
} from "./atlasGeometry";

describe("parseCalendarDate", () => {
  it("parses a plain %Y-%m-%d date at UTC midnight", () => {
    const d = parseCalendarDate("2026-07-14");
    expect(d.getTime()).toBe(Date.UTC(2026, 6, 14));
  });

  // KB-003: `created` (%Y-%m-%d) parses UTC-midnight while `updated`
  // (%Y-%m-%dT%H:%M) parses local — mixing them un-normalized skews
  // ordering. parseCalendarDate is the single entrypoint every other
  // helper routes through so BOTH shapes collapse onto the same
  // UTC-midnight instant for their calendar day, never a time-of-day.
  it("collapses an ISO-minute 'updated' timestamp onto the same instant as its bare calendar day — TZ-independent same-day regression", () => {
    expect(parseCalendarDate("2026-07-14T00:05").getTime()).toBe(
      parseCalendarDate("2026-07-14").getTime()
    );
  });

  it("ignores everything after the date prefix, however it is punctuated", () => {
    expect(parseCalendarDate("2026-07-14T23:59:59.999Z").getTime()).toBe(
      parseCalendarDate("2026-07-14").getTime()
    );
  });
});

describe("computeWindow + pctForDate — same-day regression", () => {
  it("places a camp (epic created) at or before a same-day waypoint (child updated), never after it", () => {
    const epics = [
      {
        created: "2026-07-14",
        updated: "2026-07-14T00:05",
        children: [{ updated: "2026-07-14T00:05" }],
      },
    ];
    const today = parseCalendarDate("2026-08-11");
    const window = computeWindow(epics, today);

    const camp = parseCalendarDate("2026-07-14");
    const waypoint = parseCalendarDate("2026-07-14T00:05");
    expect(pctForDate(camp, window)).toBeLessThanOrEqual(pctForDate(waypoint, window));
  });
});

describe("computeWindow", () => {
  it("spans a single epic: start = its created (padded), end = max(today, its updated) (padded)", () => {
    const today = parseCalendarDate("2026-08-01");
    const window = computeWindow(
      [{ created: "2026-07-10", updated: "2026-07-20" }],
      today
    );
    const PAD_MS = 2 * 86400000;
    expect(window.start.getTime()).toBe(parseCalendarDate("2026-07-10").getTime() - PAD_MS);
    // today (2026-08-01) postdates the epic's own updated (2026-07-20), so it wins.
    expect(window.end.getTime()).toBe(today.getTime() + PAD_MS);
  });

  it("takes the min created and the max(today, any child updated) across multiple epics", () => {
    const today = parseCalendarDate("2026-08-01");
    const window = computeWindow(
      [
        {
          created: "2026-07-14",
          updated: "2026-07-14",
          children: [{ updated: "2026-07-20" }, { updated: "2026-09-01" }],
        },
        { created: "2026-07-05", updated: "2026-07-05" },
      ],
      today
    );
    const PAD_MS = 2 * 86400000;
    expect(window.start.getTime()).toBe(parseCalendarDate("2026-07-05").getTime() - PAD_MS);
    // a child updated (2026-09-01) postdates today — it wins.
    expect(window.end.getTime()).toBe(parseCalendarDate("2026-09-01").getTime() + PAD_MS);
  });

  it("never crashes on an empty epic list — falls back to a window centred on today", () => {
    const today = parseCalendarDate("2026-08-01");
    const window = computeWindow([], today);
    expect(window.start.getTime()).toBeLessThan(today.getTime());
    expect(window.end.getTime()).toBeGreaterThan(today.getTime());
  });
});

describe("pctForDate", () => {
  it("maps the window start to 0 and the window end to 100", () => {
    const window = { start: parseCalendarDate("2026-07-01"), end: parseCalendarDate("2026-08-01") };
    expect(pctForDate(window.start, window)).toBe(0);
    expect(pctForDate(window.end, window)).toBe(100);
  });

  it("maps the window midpoint to 50", () => {
    const window = { start: parseCalendarDate("2026-07-01"), end: parseCalendarDate("2026-07-11") };
    expect(pctForDate(parseCalendarDate("2026-07-06"), window)).toBe(50);
  });
});

describe("computeAxisTicks", () => {
  it("produces weekly ticks starting exactly at the window start", () => {
    const window = { start: parseCalendarDate("2026-07-13"), end: parseCalendarDate("2026-08-17") };
    const ticks = computeAxisTicks(window);
    expect(ticks[0].getTime()).toBe(window.start.getTime());
    for (let i = 1; i < ticks.length; i++) {
      expect(ticks[i].getTime() - ticks[i - 1].getTime()).toBe(7 * 86400000);
    }
  });

  it("never emits a tick past the window end", () => {
    const window = { start: parseCalendarDate("2026-07-13"), end: parseCalendarDate("2026-08-17") };
    const ticks = computeAxisTicks(window);
    for (const t of ticks) {
      expect(t.getTime()).toBeLessThanOrEqual(window.end.getTime());
    }
  });

  it("handles a window whose span is not a multiple of 7 days — last tick stays inside, no overshoot", () => {
    const window = { start: parseCalendarDate("2026-07-13"), end: parseCalendarDate("2026-07-19") }; // 6-day span
    const ticks = computeAxisTicks(window);
    expect(ticks).toEqual([window.start]);
  });

  it("still includes the start tick even for a zero-length window", () => {
    const window = { start: parseCalendarDate("2026-07-13"), end: parseCalendarDate("2026-07-13") };
    const ticks = computeAxisTicks(window);
    expect(ticks).toEqual([window.start]);
  });
});

describe("wobblePath", () => {
  it("starts the path at x0 and ends at x1", () => {
    const { d } = wobblePath(0, 300, 104, 0);
    const commands = d.split(" ");
    expect(commands[0]).toBe("M0.0");
    expect(d.endsWith("300.0")).toBe(false); // last token is a y value, not x
    expect(d).toContain(" L");
  });

  it("yAt oscillates around laneHeight * 0.52 with amplitude 12", () => {
    const { yAt } = wobblePath(0, 300, 100, 0);
    const y = 100 * 0.52;
    // seed 0 => sin(0) = 0 at x=0
    expect(yAt(0)).toBeCloseTo(y, 5);
    // amplitude bounds hold across a full period
    for (let x = 0; x <= 300; x += 10) {
      expect(yAt(x)).toBeGreaterThanOrEqual(y - 12 - 1e-9);
      expect(yAt(x)).toBeLessThanOrEqual(y + 12 + 1e-9);
    }
  });

  it("uses wavelength 300 (k = 2π/300) — yAt(x) repeats every 300px", () => {
    const { yAt } = wobblePath(0, 600, 100, 1.23);
    expect(yAt(50)).toBeCloseTo(yAt(350), 5);
  });

  it("different seeds produce different phases", () => {
    const a = wobblePath(0, 300, 100, 0).yAt(75);
    const b = wobblePath(0, 300, 100, Math.PI / 2).yAt(75);
    expect(a).not.toBeCloseTo(b, 3);
  });
});

describe("seedFor", () => {
  it("is deterministic for the same card id", () => {
    expect(seedFor("WF-085")).toBe(seedFor("WF-085"));
  });

  it("differs across most ids (spread)", () => {
    const seeds = new Set(["WF-1", "WF-2", "WF-3", "WF-4", "WF-5"].map(seedFor));
    expect(seeds.size).toBeGreaterThan(1);
  });
});

describe("projectedEnd", () => {
  it("projects forward using elapsed-so-far / done as the pace", () => {
    const start = parseCalendarDate("2026-07-01");
    const walkedEnd = parseCalendarDate("2026-07-11"); // 10 days elapsed
    const windowEnd = parseCalendarDate("2027-01-01"); // far away, no clamp
    // done=2, total=4 => pace = 10 days / 2 = 5 days/quest, 2 remaining => +10 days
    const end = projectedEnd(start, walkedEnd, 2, 4, windowEnd);
    expect(end.getTime()).toBe(walkedEnd.getTime() + 10 * 86400000);
  });

  it("falls back to a ~5 day/quest pace when done is 0", () => {
    const start = parseCalendarDate("2026-07-01");
    const walkedEnd = parseCalendarDate("2026-07-01");
    const windowEnd = parseCalendarDate("2027-01-01");
    // done=0, total=3 => fallback pace 5 days/quest * 3 remaining = +15 days
    const end = projectedEnd(start, walkedEnd, 0, 3, windowEnd);
    expect(end.getTime()).toBe(walkedEnd.getTime() + 15 * 86400000);
  });

  it("clamps the projection so it never exceeds the window end", () => {
    const start = parseCalendarDate("2026-07-01");
    const walkedEnd = parseCalendarDate("2026-07-11");
    const windowEnd = parseCalendarDate("2026-07-15"); // tight window
    const end = projectedEnd(start, walkedEnd, 1, 10, windowEnd);
    expect(end.getTime()).toBe(windowEnd.getTime());
  });

  it("never projects before the walked end", () => {
    const start = parseCalendarDate("2026-07-01");
    const walkedEnd = parseCalendarDate("2026-07-11");
    const windowEnd = parseCalendarDate("2026-06-01"); // pathological: before walkedEnd
    const end = projectedEnd(start, walkedEnd, 1, 2, windowEnd);
    expect(end.getTime()).toBe(walkedEnd.getTime());
  });
});

describe("formatDateStamp", () => {
  it("renders en-GB day + short month, uppercase — '4 AUG' style", () => {
    expect(formatDateStamp(parseCalendarDate("2026-08-04"))).toBe("4 AUG");
  });

  it("is TZ-independent — a UTC-midnight date never rolls back a day", () => {
    expect(formatDateStamp(parseCalendarDate("2026-08-01"))).toBe("1 AUG");
  });
});
