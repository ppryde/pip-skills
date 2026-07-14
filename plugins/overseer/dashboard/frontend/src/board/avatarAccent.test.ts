import { describe, expect, it } from "vitest";
import { ACCENT_GROUPS, avatarAccentGroup } from "./avatarAccent";

describe("avatarAccentGroup", () => {
  it("is deterministic — the same seed always yields the same group", () => {
    const seed = "night-shift";
    const first = avatarAccentGroup(seed);
    for (let i = 0; i < 10; i++) {
      expect(avatarAccentGroup(seed)).toBe(first);
    }
  });

  it("always returns one of the 7 declared accent groups", () => {
    for (const seed of ["a", "session-42", "sess-xyz", "", "🐉"]) {
      expect(ACCENT_GROUPS).toContain(avatarAccentGroup(seed));
    }
  });

  it("does not throw on an empty string", () => {
    expect(() => avatarAccentGroup("")).not.toThrow();
  });

  it("different seeds can map to different groups (spot check, not a uniformity proof)", () => {
    const groups = new Set(
      ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"].map(
        avatarAccentGroup
      )
    );
    expect(groups.size).toBeGreaterThan(1);
  });
});
