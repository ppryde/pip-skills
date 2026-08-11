import { describe, expect, it } from "vitest";
import { beastFor } from "./beastName";

describe("beastFor", () => {
  it("is deterministic — same card id always yields the same beast", () => {
    expect(beastFor("WF-085")).toEqual(beastFor("WF-085"));
    expect(beastFor("WF-085")).toEqual(beastFor("WF-085"));
  });

  it("returns a 'The <epithet> <noun>' shaped name", () => {
    const { name } = beastFor("WF-027");
    expect(name).toMatch(/^The [\w-]+ [\w-]+$/);
  });

  it("returns a boolean horns flag and a 0|1 hueVariant", () => {
    const beast = beastFor("WF-058");
    expect(typeof beast.horns).toBe("boolean");
    expect([0, 1]).toContain(beast.hueVariant);
  });

  it("spreads distinct ids across distinct names — not every id collapses to one beast", () => {
    const ids = ["WF-001", "WF-002", "WF-003", "WF-004", "WF-005", "WF-006", "WF-007", "WF-008"];
    const names = new Set(ids.map((id) => beastFor(id).name));
    expect(names.size).toBeGreaterThan(1);
  });

  it("spreads horns across both true and false over many ids", () => {
    const ids = Array.from({ length: 40 }, (_, i) => `WF-${i}`);
    const hornsValues = new Set(ids.map((id) => beastFor(id).horns));
    expect(hornsValues.size).toBe(2);
  });

  it("spreads hueVariant across both 0 and 1 over many ids", () => {
    const ids = Array.from({ length: 40 }, (_, i) => `WF-${i}`);
    const hueValues = new Set(ids.map((id) => beastFor(id).hueVariant));
    expect(hueValues.size).toBe(2);
  });
});
