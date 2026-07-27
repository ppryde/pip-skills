import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useRepos } from "./useRepos";
import * as client from "../api/client";

vi.mock("../api/client");

describe("useRepos", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("fetches on mount and returns the discovered repos", async () => {
    const mockGetRepos = vi.mocked(client.getRepos);
    mockGetRepos.mockResolvedValueOnce({
      repos: [{ label: "repo-a", root: "/a", current: true }],
    });

    const { result } = renderHook(() => useRepos());

    await waitFor(() => {
      expect(result.current.repos).toHaveLength(1);
    });
    expect(result.current.repos[0].label).toBe("repo-a");
  });

  it("swallows a mount-fetch failure and returns an empty list", async () => {
    const mockGetRepos = vi.mocked(client.getRepos);
    mockGetRepos.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useRepos());

    await waitFor(() => {
      expect(mockGetRepos).toHaveBeenCalled();
    });
    expect(result.current.repos).toEqual([]);
  });

  it("does not throw on unmount while a fetch may still be in flight", async () => {
    const mockGetRepos = vi.mocked(client.getRepos);
    mockGetRepos.mockResolvedValue({
      repos: [{ label: "repo-a", root: "/a", current: true }],
    });

    const { unmount } = renderHook(() => useRepos());

    expect(() => {
      unmount();
    }).not.toThrow();
  });
});
