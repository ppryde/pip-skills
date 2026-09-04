import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatDuration,
  formatActive,
  formatDay,
  niceTicks,
  repoLabel,
  sessionName,
  shortModel,
} from "./format";

describe("formatBytes", () => {
  it("bands by 1024", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(91148426)).toBe("86.9 MB");
    expect(formatBytes(120 * 1024 * 1024)).toBe("120 MB");
    expect(formatBytes(-1)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("picks the coarsest useful unit", () => {
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(720)).toBe("12m");
    expect(formatDuration(3 * 3600 + 5 * 60)).toBe("3h 05m");
    expect(formatDuration(2 * 86400 + 4 * 3600)).toBe("2d 4h");
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(-5)).toBe("—");
  });

  it("formatActive treats 0ms as unknown", () => {
    expect(formatActive(0)).toBe("—");
    expect(formatActive(90_000)).toBe("1m");
  });
});

describe("formatDay", () => {
  it("renders an ISO day as day + short month", () => {
    expect(formatDay("2026-09-04")).toMatch(/4/);
    expect(formatDay("2026-09-04")).toMatch(/Sep/);
    expect(formatDay("garbage")).toBe("garbage");
  });
});

describe("niceTicks", () => {
  it("returns round steps that cover the max", () => {
    expect(niceTicks(0)).toEqual([0]);
    expect(niceTicks(9)).toEqual([0, 5, 10]);
    expect(niceTicks(7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(4700)).toEqual([0, 2000, 4000, 6000]);
    const ticks = niceTicks(4_688_945_726);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(4_688_945_726);
    expect(ticks.length).toBeLessThanOrEqual(7);
  });
});

describe("labels", () => {
  it("shortModel strips the vendor prefix", () => {
    expect(shortModel("claude-fable-5-1")).toBe("fable-5-1");
    expect(shortModel(null)).toBe("unknown");
  });

  it("sessionName prefers the title, else the id prefix", () => {
    expect(sessionName({ title: " Fix widget ", session_id: "abcdef12-rest" })).toBe("Fix widget");
    expect(sessionName({ title: null, session_id: "abcdef12-rest" })).toBe("abcdef12");
  });

  it("repoLabel is the last path segment", () => {
    expect(repoLabel("/Users/x/repos/pip-skills")).toBe("pip-skills");
    expect(repoLabel(null)).toBe("—");
  });
});
