import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  getAlmonerDigest: vi.fn(),
  getAlmonerStatus: vi.fn(),
}));

import * as client from "../../api/client";
import { useAlmonerDigest } from "./useAlmoner";

const mocked = client as unknown as { getAlmonerDigest: ReturnType<typeof vi.fn> };

/** `refresh()` chains several `.then`s off a mocked, already-resolved
 * promise. A macrotask boundary (unlike a fixed number of microtask
 * `await`s) drains every one of them regardless of how deep the chain is. */
async function flush() {
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

describe("useAlmonerDigest", () => {
  afterEach(() => vi.clearAllMocks());

  it("treats a genuinely empty digest as success, not an error", async () => {
    mocked.getAlmonerDigest.mockResolvedValue({ items: [], sources: [] });
    const { result } = renderHook(() => useAlmonerDigest());
    act(() => result.current.refresh());
    await flush();

    expect(result.current.digest).toEqual({ items: [], sources: [] });
    expect(result.current.error).toBeNull();
    expect(result.current.refreshedAt).not.toBeNull();
  });

  it("treats a 200 carrying `error` as a failure, not an empty digest", async () => {
    // The backend answers 200 even when the almoner CLI itself failed —
    // timeout, non-zero exit, bad JSON — with `error` set alongside the same
    // empty `items`/`sources` a genuinely empty digest would carry. Byte-
    // identical shapes there would render as "nothing needs you", which the
    // design explicitly forbids: a silently-short digest is worse than a
    // visible failure.
    mocked.getAlmonerDigest.mockResolvedValue({
      items: [],
      sources: [],
      error: "almoner did not return a digest",
    });
    const { result } = renderHook(() => useAlmonerDigest());
    act(() => result.current.refresh());
    await flush();

    expect(result.current.error).toBe("almoner did not return a digest");
    // Never rendered as a successful, merely-empty digest.
    expect(result.current.digest).toBeNull();
  });

  it("does not stamp a refresh time for a run that came back marked as failed", async () => {
    mocked.getAlmonerDigest.mockResolvedValue({ items: [], sources: [], error: "boom" });
    const { result } = renderHook(() => useAlmonerDigest());
    act(() => result.current.refresh());
    await flush();

    expect(result.current.refreshedAt).toBeNull();
  });
});
