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
});
