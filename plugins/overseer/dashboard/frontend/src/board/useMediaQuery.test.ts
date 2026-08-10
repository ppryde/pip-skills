import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useMediaQuery } from "./useMediaQuery";

/** Minimal `MediaQueryList` stub — enough for the hook's read + listener
 * wiring, with a `fire()` helper tests use to simulate a viewport change. */
function stubMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  let listener: (() => void) | undefined;
  const mql = {
    get matches() {
      return matches;
    },
    media: "",
    addEventListener: (_: string, cb: () => void) => {
      listener = cb;
    },
    removeEventListener: () => {
      listener = undefined;
    },
  };
  return {
    mql: mql as unknown as MediaQueryList,
    fire: (next: boolean) => {
      matches = next;
      act(() => listener?.());
    },
  };
}

const originalMatchMedia = window.matchMedia;

describe("useMediaQuery", () => {
  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it("returns the current matchMedia result", () => {
    const { mql } = stubMatchMedia(true);
    window.matchMedia = vi.fn().mockReturnValue(mql);

    const { result } = renderHook(() => useMediaQuery("(max-width:720px)"));

    expect(result.current).toBe(true);
  });

  it("returns false when matchMedia reports no match", () => {
    const { mql } = stubMatchMedia(false);
    window.matchMedia = vi.fn().mockReturnValue(mql);

    const { result } = renderHook(() => useMediaQuery("(max-width:720px)"));

    expect(result.current).toBe(false);
  });

  it("updates when the underlying media query result changes", () => {
    const { mql, fire } = stubMatchMedia(false);
    window.matchMedia = vi.fn().mockReturnValue(mql);

    const { result } = renderHook(() => useMediaQuery("(max-width:720px)"));
    expect(result.current).toBe(false);

    fire(true);

    expect(result.current).toBe(true);
  });

  it("is safe (returns false) when matchMedia is absent from window", () => {
    // @ts-expect-error — simulating an environment without matchMedia at all.
    delete window.matchMedia;

    const { result } = renderHook(() => useMediaQuery("(max-width:720px)"));

    expect(result.current).toBe(false);
  });
});
