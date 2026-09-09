import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDismiss } from "./useDismiss";

function escape() {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
}

describe("useDismiss", () => {
  it("closes on Escape", () => {
    const onDismiss = vi.fn();
    renderHook(() => useDismiss(onDismiss));
    escape();
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("ignores every other key", () => {
    const onDismiss = vi.fn();
    renderHook(() => useDismiss(onDismiss));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("unwinds ONE layer per press — the innermost", () => {
    // The whole point. Nine independent listeners meant one press reached
    // every open overlay, which is why a stacked pair had to negotiate with
    // capture-phase handlers and stopPropagation.
    const outer = vi.fn();
    const inner = vi.fn();
    renderHook(() => useDismiss(outer));
    const innerLayer = renderHook(() => useDismiss(inner));

    escape();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();

    // With the inner layer gone the next press reaches the one beneath it.
    innerLayer.unmount();
    escape();
    expect(outer).toHaveBeenCalledTimes(1);
    expect(inner).toHaveBeenCalledTimes(1);
  });

  it("leaves a disabled layer off the stack entirely", () => {
    // How a component that KNOWS it is not the top layer says so — a
    // question about state, not a race between listeners.
    const outer = vi.fn();
    const inner = vi.fn();
    renderHook(() => useDismiss(outer, false));
    renderHook(() => useDismiss(inner));
    escape();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it("registers a layer when it becomes enabled, and drops it when it stops", () => {
    const onDismiss = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }) => useDismiss(onDismiss, enabled),
      { initialProps: { enabled: false } }
    );
    escape();
    expect(onDismiss).not.toHaveBeenCalled();

    rerender({ enabled: true });
    escape();
    expect(onDismiss).toHaveBeenCalledTimes(1);

    rerender({ enabled: false });
    escape();
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls the LATEST callback without re-registering the layer", () => {
    // A caller passing a fresh closure each render must not be re-pushed —
    // that would jump it ahead of a layer opened above it.
    const first = vi.fn();
    const second = vi.fn();
    const top = vi.fn();
    const { rerender } = renderHook(({ fn }) => useDismiss(fn), { initialProps: { fn: first } });
    renderHook(() => useDismiss(top));

    rerender({ fn: second });
    escape();
    expect(top).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
  });

  it("installs one listener for the whole app and removes it with the last layer", () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const a = renderHook(() => useDismiss(vi.fn()));
    const b = renderHook(() => useDismiss(vi.fn()));
    const keydownAdds = add.mock.calls.filter(([type]) => type === "keydown");
    expect(keydownAdds).toHaveLength(1);

    a.unmount();
    expect(remove.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(0);
    b.unmount();
    expect(remove.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(1);
    add.mockRestore();
    remove.mockRestore();
  });

  it("does nothing at all once every layer has closed", () => {
    const onDismiss = vi.fn();
    const layer = renderHook(() => useDismiss(onDismiss));
    layer.unmount();
    escape();
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
