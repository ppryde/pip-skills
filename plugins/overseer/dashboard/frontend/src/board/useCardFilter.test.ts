import { beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useCardFilter } from "./useCardFilter";
import { DEFAULT_FILTER } from "./cardFilter";

describe("useCardFilter", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to future-excluded", () => {
    const { result } = renderHook(() => useCardFilter());
    expect(result.current.filter.excludeLabels).toEqual(["future"]);
  });

  it("cycleLabel goes neutral -> include -> exclude -> neutral", () => {
    const { result } = renderHook(() => useCardFilter());

    act(() => result.current.cycleLabel("ui"));
    expect(result.current.filter.includeLabels).toContain("ui");
    expect(result.current.filter.excludeLabels).not.toContain("ui");

    act(() => result.current.cycleLabel("ui"));
    expect(result.current.filter.excludeLabels).toContain("ui");
    expect(result.current.filter.includeLabels).not.toContain("ui");

    act(() => result.current.cycleLabel("ui"));
    expect(result.current.filter.includeLabels).not.toContain("ui");
    expect(result.current.filter.excludeLabels).not.toContain("ui");
  });

  it("clear resets to default (future excluded, not empty)", () => {
    const { result } = renderHook(() => useCardFilter());

    act(() => {
      result.current.setQuery("x");
      result.current.cycleLabel("ui");
      result.current.clear();
    });

    expect(result.current.filter).toEqual({
      query: "",
      includeLabels: [],
      excludeLabels: ["future"],
      priority: null,
      complexity: null,
    });
  });

  it("persists to and restores from localStorage", () => {
    const { result, unmount } = renderHook(() => useCardFilter());

    act(() => result.current.setPriority("P0"));
    unmount();

    const { result: r2 } = renderHook(() => useCardFilter());
    expect(r2.current.filter.priority).toBe("P0");
  });

  it("falls back to default on corrupt localStorage", () => {
    localStorage.setItem("overseer_board_filter", "{not json");

    const { result } = renderHook(() => useCardFilter());
    expect(result.current.filter).toEqual(DEFAULT_FILTER);
  });

  it("falls back to default when localStorage is absent", () => {
    const { result } = renderHook(() => useCardFilter());
    expect(result.current.filter).toEqual(DEFAULT_FILTER);
  });

  it("setQuery and setComplexity update filter state", () => {
    const { result } = renderHook(() => useCardFilter());

    act(() => {
      result.current.setQuery("board");
      result.current.setComplexity("M");
    });

    expect(result.current.filter.query).toBe("board");
    expect(result.current.filter.complexity).toBe("M");
  });
});
