import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useAccounts } from "./useAccounts";
import * as client from "../api/client";

vi.mock("../api/client");

describe("useAccounts", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("fetches on mount and returns the discovered accounts", async () => {
    const mockGetAccounts = vi.mocked(client.getAccounts);
    mockGetAccounts.mockResolvedValueOnce({
      accounts: [
        {
          account_uuid: "11111111-aaaa",
          short_uuid: "11111111",
          plan: "claude_max",
          config_dirs: ["/home/x/.claude"],
          sessions: 3,
          last_activity_at: 100,
        },
      ],
    });

    const { result } = renderHook(() => useAccounts());

    await waitFor(() => {
      expect(result.current.accounts).toHaveLength(1);
    });
    expect(result.current.accounts[0].account_uuid).toBe("11111111-aaaa");
  });

  it("swallows a mount-fetch failure and returns an empty list", async () => {
    const mockGetAccounts = vi.mocked(client.getAccounts);
    mockGetAccounts.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useAccounts());

    await waitFor(() => {
      expect(mockGetAccounts).toHaveBeenCalled();
    });
    expect(result.current.accounts).toEqual([]);
  });

  it("does not throw on unmount while a fetch may still be in flight", async () => {
    const mockGetAccounts = vi.mocked(client.getAccounts);
    mockGetAccounts.mockResolvedValue({
      accounts: [
        {
          account_uuid: "11111111-aaaa",
          short_uuid: "11111111",
          plan: null,
          config_dirs: [],
          sessions: 0,
          last_activity_at: null,
        },
      ],
    });

    const { unmount } = renderHook(() => useAccounts());

    expect(() => {
      unmount();
    }).not.toThrow();
  });
});
