import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.mock("../../api/client", () => ({ syncChronicle: vi.fn() }));

import * as client from "../../api/client";
import { AUTO_SYNC_INTERVAL_MS, useChronicleSync } from "./useChronicle";

const mocked = client as unknown as { syncChronicle: ReturnType<typeof vi.fn> };
const nothingNew = { scanned: 3, changed: 0, lines: 0, sessions: [], synced_at: 1 };
const oneChanged = { scanned: 3, changed: 1, lines: 12, sessions: ["a"], synced_at: 2 };

describe("useChronicleSync", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocked.syncChronicle.mockResolvedValue(nothingNew);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("the button's sync always leaves a note and refreshes", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useChronicleSync(refresh));
    await act(() => result.current.sync());
    expect(result.current.note).toMatch(/nothing new across 3 files/);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("while enabled, syncs quietly on enable and every minute, noting only real changes", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useChronicleSync(refresh, true));
    await act(async () => {});
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(1);
    expect(mocked.syncChronicle).toHaveBeenCalledWith({ quiet: true }); // never the token prompt
    expect(result.current.note).toBeNull(); // nothing new: silence
    expect(refresh).not.toHaveBeenCalled();

    mocked.syncChronicle.mockResolvedValueOnce(oneChanged);
    await act(async () => {
      vi.advanceTimersByTime(AUTO_SYNC_INTERVAL_MS);
    });
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(2);
    expect(result.current.note).toMatch(/1 session updated/);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not sync quietly when disabled, and swallows failures when it does", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ on }) => useChronicleSync(refresh, on), { initialProps: { on: false } });
    await act(async () => {});
    expect(mocked.syncChronicle).not.toHaveBeenCalled();

    mocked.syncChronicle.mockRejectedValueOnce(new Error("boom"));
    rerender({ on: true });
    await act(async () => {});
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(1);
    expect(result.current.note).toBeNull();
    expect(result.current.syncing).toBe(false);
  });

  it("pauses while the tab is hidden and catches up once when it returns", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const hidden = vi.spyOn(document, "hidden", "get");
    hidden.mockReturnValue(false);
    renderHook(() => useChronicleSync(refresh, true));
    await act(async () => {});
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(1);

    // Backgrounded: the minute ticks do nothing.
    hidden.mockReturnValue(true);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(async () => {
      vi.advanceTimersByTime(AUTO_SYNC_INTERVAL_MS * 3);
    });
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(1);

    // Foreground again: one catch-up sync (the last one is well past the min gap).
    hidden.mockReturnValue(false);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(2);
    hidden.mockRestore();
  });

  it("skips a quiet sync that follows another too closely", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useChronicleSync(refresh));
    await act(() => result.current.syncQuietly());
    await act(() => result.current.syncQuietly());
    expect(mocked.syncChronicle).toHaveBeenCalledTimes(1);
    expect(result.current.syncing).toBe(false); // the quiet path never shows busy
  });
});
