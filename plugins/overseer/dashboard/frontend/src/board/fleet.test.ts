import { describe, expect, it } from "vitest";
import { fleetSummary } from "./fleet";
import type { SessionSummary } from "../api/types";

function session(overrides: Partial<SessionSummary> & { id: string }): SessionSummary {
  return {
    worktree_cwd: "/w",
    updated_at: 100,
    stale: false,
    ...overrides,
  };
}

describe("fleetSummary", () => {
  it("returns a safe zero-state for an empty fleet — no NaN, no sessions", () => {
    expect(fleetSummary([], null)).toEqual({
      questing: 0,
      topCtx: null,
      nearThreshold: 0,
    });
  });

  it("questing counts only live (non-stale) sessions", () => {
    const result = fleetSummary(
      [
        session({ id: "s1", stale: false }),
        session({ id: "s2", stale: false }),
        session({ id: "s3", stale: true }),
      ],
      null
    );
    expect(result.questing).toBe(2);
  });

  it("topCtx is the max pct among live sessions", () => {
    const result = fleetSummary(
      [
        session({ id: "s1", pct: 40 }),
        session({ id: "s2", pct: 86 }),
        session({ id: "s3", pct: 55 }),
      ],
      null
    );
    expect(result.topCtx).toBe(86);
  });

  it("topCtx ignores a stale session even if its pct would otherwise be the max", () => {
    const result = fleetSummary(
      [
        session({ id: "s1", pct: 40 }),
        session({ id: "s2", pct: 99, stale: true }),
      ],
      null
    );
    expect(result.topCtx).toBe(40);
  });

  it("topCtx is null when no live session carries a pct", () => {
    const result = fleetSummary(
      [session({ id: "s1" }), session({ id: "s2", stale: true, pct: 90 })],
      null
    );
    expect(result.topCtx).toBeNull();
  });

  it("nearThreshold counts live sessions with pct >= threshold", () => {
    const result = fleetSummary(
      [
        session({ id: "s1", pct: 90 }),
        session({ id: "s2", pct: 80 }),
        session({ id: "s3", pct: 50 }),
      ],
      80
    );
    expect(result.nearThreshold).toBe(2);
  });

  it("nearThreshold excludes stale sessions even above threshold", () => {
    const result = fleetSummary(
      [session({ id: "s1", pct: 95, stale: true })],
      80
    );
    expect(result.nearThreshold).toBe(0);
  });

  it("nearThreshold is 0 when threshold is null, regardless of pct", () => {
    const result = fleetSummary([session({ id: "s1", pct: 99 })], null);
    expect(result.nearThreshold).toBe(0);
  });

  it("nearThreshold ignores sessions with no pct", () => {
    const result = fleetSummary([session({ id: "s1" })], 0);
    expect(result.nearThreshold).toBe(0);
  });
});
