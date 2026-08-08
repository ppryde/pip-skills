import { describe, expect, it } from "vitest";
import { rarityStars } from "./rarityStars";

describe("rarityStars", () => {
  it("maps S to 1 star", () => {
    expect(rarityStars("S")).toBe(1);
  });

  it("maps M to 2 stars", () => {
    expect(rarityStars("M")).toBe(2);
  });

  it("maps L to 3 stars", () => {
    expect(rarityStars("L")).toBe(3);
  });

  it("maps null to 0 stars", () => {
    expect(rarityStars(null)).toBe(0);
  });

  it("maps an unrecognised value to 0 stars rather than guessing", () => {
    expect(rarityStars("XL")).toBe(0);
    expect(rarityStars("")).toBe(0);
    expect(rarityStars("s")).toBe(0);
  });
});
