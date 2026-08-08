import { describe, expect, it } from "vitest";
import { formatTokens } from "./formatTokens";

describe("formatTokens", () => {
  it("returns 0 verbatim", () => {
    expect(formatTokens(0)).toBe("0");
  });

  it("returns sub-1k values verbatim", () => {
    expect(formatTokens(950)).toBe("950");
  });

  it("shows one decimal for non-round values under 10k", () => {
    expect(formatTokens(1500)).toBe("1.5k");
  });

  it("trims a round value under 10k to no decimal", () => {
    expect(formatTokens(1000)).toBe("1k");
  });

  it("rounds to the nearest k with no decimal at 10k and above", () => {
    expect(formatTokens(30000)).toBe("30k");
    expect(formatTokens(254000)).toBe("254k");
  });

  it("rounds a non-exact k value at 10k and above", () => {
    expect(formatTokens(12345)).toBe("12k");
  });

  it("never shows 1000k — rounding at the k/M boundary falls into the M band", () => {
    expect(formatTokens(999_499)).toBe("999k");
    expect(formatTokens(999_500)).toBe("1M");
    expect(formatTokens(999_999)).toBe("1M");
  });

  it("shows one decimal in the millions band", () => {
    expect(formatTokens(1_200_000)).toBe("1.2M");
  });

  it("trims a round millions value to no decimal", () => {
    expect(formatTokens(2_000_000)).toBe("2M");
  });
});
