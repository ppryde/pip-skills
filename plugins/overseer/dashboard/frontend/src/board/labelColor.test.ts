import { describe, expect, it } from "vitest";
import { labelColor } from "./labelColor";

const PALETTE_KEYS = [
  "slate",
  "sage",
  "plum",
  "clay",
  "sky",
  "violet",
  "olive",
  "terracotta",
  "teal",
];

describe("labelColor", () => {
  it("is stable across repeated calls for the same label", () => {
    expect(labelColor("policy")).toBe(labelColor("policy"));
    expect(labelColor("policy")).toBe(labelColor("policy"));
  });

  it("usually differs between distinct labels", () => {
    expect(labelColor("policy")).not.toBe(labelColor("architecture"));
  });

  it("always returns one of the curated palette keys", () => {
    expect(PALETTE_KEYS).toContain(labelColor("anything"));
    expect(PALETTE_KEYS).toContain(labelColor(""));
    expect(PALETTE_KEYS).toContain(labelColor("a-much-longer-label-string"));
  });

  it("is a pure function of the label — no hidden per-render/global state", () => {
    const a = labelColor("policy");
    const b = labelColor("architecture");
    const c = labelColor("policy");
    expect(c).toBe(a);
    expect(a === b).toBe(labelColor("policy") === labelColor("architecture"));
  });

  describe("with a registry (F10, WF-067)", () => {
    it("returns the registry's chosen key on a hit, even if it differs from the hash palette", () => {
      // Deliberately picks whatever the hash would NOT have picked, so a
      // passing assertion proves the registry actually won, not that it
      // happened to agree with the fallback.
      const hashKey = labelColor("policy");
      const overrideKey = PALETTE_KEYS.find((k) => k !== hashKey)!;
      expect(labelColor("policy", { policy: overrideKey })).toBe(overrideKey);
    });

    it("falls back to the SAME hash palette key when the registry has no entry for the label", () => {
      expect(labelColor("policy", {})).toBe(labelColor("policy"));
      expect(labelColor("policy", { architecture: "sky" })).toBe(
        labelColor("policy")
      );
    });

    it("an undefined registry (no 2nd arg) behaves identically to an empty one", () => {
      expect(labelColor("policy", undefined)).toBe(labelColor("policy", {}));
    });
  });
});
