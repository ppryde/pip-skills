import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useVisibleInterval } from "./useDocumentVisible";

function setHidden(spy: ReturnType<typeof vi.spyOn>, hidden: boolean) {
  spy.mockReturnValue(hidden);
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

describe("useVisibleInterval on-return", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("fires a catch-up tick only when the page returns from hidden while enabled", () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const tick = vi.fn();
    renderHook(() => useVisibleInterval(tick, 60_000, true, { immediate: "on-return" }));
    expect(tick).not.toHaveBeenCalled(); // first showing is not a return
    setHidden(hidden, true);
    setHidden(hidden, false);
    expect(tick).toHaveBeenCalledTimes(1);
  });

  it("does not count a hide/show cycle seen while disabled as a return", () => {
    // The board is up (chronicle's poller disabled); the tab is hidden and
    // shown again; then the person opens Chronicle. The page's own
    // load-on-enable fetches — this hook must not add a second one.
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const tick = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useVisibleInterval(tick, 60_000, enabled, { immediate: "on-return" }),
      { initialProps: { enabled: false } }
    );
    setHidden(hidden, true);
    setHidden(hidden, false);
    rerender({ enabled: true });
    expect(tick).not.toHaveBeenCalled();
    // A hide while enabled, then a disable and re-enable: still not a return.
    setHidden(hidden, true);
    rerender({ enabled: false });
    setHidden(hidden, false);
    rerender({ enabled: true });
    expect(tick).not.toHaveBeenCalled();
    // Once enabled and visible, the interval ticks as normal.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(tick).toHaveBeenCalledTimes(1);
  });
});
