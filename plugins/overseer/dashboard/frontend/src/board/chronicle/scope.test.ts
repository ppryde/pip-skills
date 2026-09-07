import { describe, expect, it } from "vitest";
import type { RepoEntry } from "../../api/types";
import { chronicleScopeFor, isChronicleScopable } from "./scope";

function repo(over: Partial<RepoEntry>): RepoEntry {
  return { label: "r", root: "/r", current: false, has_board: true, live_sessions: 0, ...over };
}

describe("chronicle scope", () => {
  it("scopes to a repo chronicle knows, board or no board", () => {
    // The WF-108 case: months of sessions, no board ever raised.
    expect(isChronicleScopable(repo({ has_board: false, chronicled: true }))).toBe(true);
    expect(chronicleScopeFor(repo({ has_board: false, chronicled: true }), false)).toBe("repo");
  });

  it("pins a repo chronicle has never seen to All repos", () => {
    // Naming it would 400, so the page must not try.
    expect(isChronicleScopable(repo({ has_board: false, chronicled: false }))).toBe(false);
    expect(chronicleScopeFor(repo({ has_board: false, chronicled: false }), false)).toBe("all");
  });

  it("falls back to has_board when the backend predates the flag", () => {
    expect(isChronicleScopable(repo({ has_board: true }))).toBe(true);
    expect(isChronicleScopable(repo({ has_board: false }))).toBe(false);
  });

  it("no selection scopes normally — the server uses its own launch root", () => {
    expect(isChronicleScopable(null)).toBe(true);
    expect(chronicleScopeFor(null, false)).toBe("repo");
  });

  it("an explicit All repos always wins", () => {
    expect(chronicleScopeFor(repo({ chronicled: true }), true)).toBe("all");
  });
});
