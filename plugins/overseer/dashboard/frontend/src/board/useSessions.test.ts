import { describe, expect, it, vi, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useSessions } from "./useSessions";
import * as client from "../api/client";

vi.mock("../api/client");

describe("useSessions", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("fetches on mount and returns the sessions", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValueOnce({
      sessions: [
        { id: "s1", worktree_cwd: "/w/a", updated_at: 100, stale: false },
      ],
    });

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.sessions).toHaveLength(1);
    });
    expect(result.current.sessions[0].id).toBe("s1");
  });

  it("orders sessions most recently active first", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValueOnce({
      sessions: [
        { id: "oldest", worktree_cwd: "/w/a", updated_at: 100, stale: true },
        { id: "newest", worktree_cwd: "/w/b", updated_at: 300, stale: false },
        { id: "middle", worktree_cwd: "/w/c", updated_at: 200, stale: false },
      ],
    });

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.sessions).toHaveLength(3);
    });
    expect(result.current.sessions.map((s) => s.id)).toEqual([
      "newest",
      "middle",
      "oldest",
    ]);
  });

  it("swallows a mount-fetch failure and returns an empty list", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(mockGetSessions).toHaveBeenCalled();
    });
    expect(result.current.sessions).toEqual([]);
  });

  it("polls again after 5s and reflects the new response", async () => {
    vi.useFakeTimers();
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions
      .mockResolvedValueOnce({
        sessions: [{ id: "s1", worktree_cwd: "/w", updated_at: 100, stale: false }],
      })
      .mockResolvedValueOnce({
        sessions: [
          { id: "s1", worktree_cwd: "/w", updated_at: 100, stale: false },
          { id: "s2", worktree_cwd: "/w2", updated_at: 200, stale: false },
        ],
      });

    const { result } = renderHook(() => useSessions());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.sessions).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(result.current.sessions).toHaveLength(2);

    vi.useRealTimers();
  });

  it("does not throw on unmount while a fetch may still be in flight", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValue({
      sessions: [{ id: "s1", worktree_cwd: "/w", updated_at: 1, stale: false }],
    });

    const { unmount } = renderHook(() => useSessions());

    expect(() => {
      unmount();
    }).not.toThrow();
  });
});
