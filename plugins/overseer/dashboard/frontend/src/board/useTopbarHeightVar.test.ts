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

  // Impl-review round 2, finding 4: a residual gap was observed in the real
  // browser, suspected to be the topbar's height caught BEFORE its wrapped
  // rows fully settled (e.g. async content pushing it to another row,
  // right after the very first synchronous layout pass this hook's
  // initial measurement runs in).
  it("re-measures once more after the next paint (requestAnimationFrame), catching a topbar that hadn't finished wrapping yet", async () => {
    const topbar = document.createElement("div");
    topbar.className = "topbar";
    document.body.appendChild(topbar);
    const heightSpy = vi.spyOn(topbar, "getBoundingClientRect");
    heightSpy.mockReturnValue({ height: 107 } as DOMRect); // mid-layout, not yet fully wrapped

    renderHook(() => useTopbarHeightVar());
    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("107px");

    // The topbar finishes wrapping to its real height between the initial
    // synchronous measurement and the next paint.
    heightSpy.mockReturnValue({ height: 187 } as DOMRect);

    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    });

    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("187px");
  });

  it("re-measures fresh when remeasureKey changes (a breakpoint crossing) rather than relying on the observer's own timing", () => {
    const topbar = document.createElement("div");
    topbar.className = "topbar";
    document.body.appendChild(topbar);
    const heightSpy = vi.spyOn(topbar, "getBoundingClientRect");
    heightSpy.mockReturnValue({ height: 64 } as DOMRect); // desktop, single row

    const { rerender } = renderHook(({ isMobile }) => useTopbarHeightVar(isMobile), {
      initialProps: { isMobile: false },
    });
    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("64px");

    // Crossing into mobile wraps the topbar to a taller, multi-row height —
    // simulated here as an already-settled measurement (the CSS media
    // query has already taken effect by the time isMobile flips), which
    // this hook must re-measure immediately rather than wait on its
    // ResizeObserver to notice.
    heightSpy.mockReturnValue({ height: 187 } as DOMRect);
    act(() => {
      rerender({ isMobile: true });
    });

    expect(document.documentElement.style.getPropertyValue(CSS_VAR)).toBe("187px");
  });
});
