import { describe, expect, it } from "vitest";
import { formatDateStamp, parseCalendarDate, seedFor, wobblePath, wobblePathVertical } from "./atlasGeometry";

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

  it("falls back to epoch 0 for a blank value, instead of NaN", () => {
    expect(parseCalendarDate("").getTime()).toBe(0);
  });

  it("falls back to epoch 0 for a garbage value, instead of NaN", () => {
    expect(parseCalendarDate("not-a-date").getTime()).toBe(0);
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

describe("wobblePathVertical", () => {
  it("starts the path at y0 and ends at y1, wobbling in x", () => {
    const { d } = wobblePathVertical(0, 300, 104, 0);
    const commands = d.split(" ");
    // "M<x> <y>" — the first token is "M<x>", so the FIRST y (second token
    // of the pair) must be y0.
    const firstPair = commands.slice(0, 2).join(" ");
    expect(firstPair.endsWith(" 0.0")).toBe(true);
    expect(d).toContain(" L");
  });

  it("xAt oscillates around laneWidth * 0.52 with amplitude 12", () => {
    const { xAt } = wobblePathVertical(0, 300, 100, 0);
    const x = 100 * 0.52;
    expect(xAt(0)).toBeCloseTo(x, 5);
    for (let y = 0; y <= 300; y += 10) {
      expect(xAt(y)).toBeGreaterThanOrEqual(x - 12 - 1e-9);
      expect(xAt(y)).toBeLessThanOrEqual(x + 12 + 1e-9);
    }
  });

  it("mirrors wobblePath's amplitude/wavelength — same yAt(x)/xAt(y) shape, axes swapped", () => {
    const across = wobblePath(0, 300, 100, 0.5).yAt(120) - 100 * 0.52;
    const down = wobblePathVertical(0, 300, 100, 0.5).xAt(120) - 100 * 0.52;
    expect(down).toBeCloseTo(across, 5);
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

describe("formatDateStamp", () => {
  it("renders en-GB day + short month, uppercase — '4 AUG' style", () => {
    expect(formatDateStamp(parseCalendarDate("2026-08-04"))).toBe("4 AUG");
  });

  it("is TZ-independent — a UTC-midnight date never rolls back a day", () => {
    expect(formatDateStamp(parseCalendarDate("2026-08-01"))).toBe("1 AUG");
  });
});
