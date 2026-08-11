import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { CSS_VAR, DEFAULT_TOPBAR_HEIGHT_PX, useTopbarHeightVar } from "./useTopbarHeightVar";

describe("useTopbarHeightVar", () => {
  afterEach(() => {
    document.documentElement.style.removeProperty(CSS_VAR);
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  it("publishes the real .topbar element's measured height as a CSS custom property on the document root", () => {
    const topbar = document.createElement("div");
    topbar.className = "topbar";
    document.body.appendChild(topbar);
    vi.spyOn(topbar, "getBoundingClientRect").mockReturnValue({ height: 96 } as DOMRect);

    renderHook(() => useTopbarHeightVar());

    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("96px");
  });

  it("re-measures on ResizeObserver callback — the topbar's real height varies as it wraps across viewport widths", () => {
    const topbar = document.createElement("div");
    topbar.className = "topbar";
    document.body.appendChild(topbar);
    vi.spyOn(topbar, "getBoundingClientRect").mockReturnValue({ height: 64 } as DOMRect);

    let capturedCallback: ResizeObserverCallback | null = null;
    class MockResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        capturedCallback = cb;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);

    renderHook(() => useTopbarHeightVar());
    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("64px");

    act(() => {
      capturedCallback!(
        [{ contentRect: { height: 148 } } as ResizeObserverEntry],
        {} as ResizeObserver
      );
    });

    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("148px");
  });

  it("falls back to the default when no .topbar element exists in the document", () => {
    renderHook(() => useTopbarHeightVar());
    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe(`${DEFAULT_TOPBAR_HEIGHT_PX}px`);
  });

  it("falls back to the default for a non-finite measurement", () => {
    const topbar = document.createElement("div");
    topbar.className = "topbar";
    document.body.appendChild(topbar);
    vi.spyOn(topbar, "getBoundingClientRect").mockReturnValue({ height: NaN } as DOMRect);

    renderHook(() => useTopbarHeightVar());
    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe(`${DEFAULT_TOPBAR_HEIGHT_PX}px`);
  });
});
