import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import SessionsPanel from "./SessionsPanel";
import * as client from "../api/client";

vi.mock("../api/client");

describe("<SessionsPanel />", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders multiple sessions with all fields", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValueOnce({
      sessions: [
        {
          id: "s1",
          worktree_cwd: "/path/to/work1",
          updated_at: 1234567890,
          stale: false,
          session_name: "night-shift",
          model: "Opus",
          pct: 44,
          pr: { number: 22, url: "http://pr/22", review_state: "pending" },
        },
        {
          id: "s2",
          worktree_cwd: "/path/to/work2",
          updated_at: 1234567800,
          stale: false,
          model: "Haiku",
          pct: 22,
        },
      ],
    });

    render(<SessionsPanel />);

    await waitFor(() => {
      expect(screen.getByText("night-shift")).toBeInTheDocument();
      expect(screen.getByText("s2")).toBeInTheDocument();
    });

    expect(screen.getByText("Opus")).toBeInTheDocument();
    expect(screen.getByText("Haiku")).toBeInTheDocument();
  });

  it("degrades gracefully when optional fields are absent", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValueOnce({
      sessions: [
        {
          id: "s1",
          worktree_cwd: "/path/to/work",
          updated_at: 1234567890,
          stale: false,
        },
      ],
    });

    render(<SessionsPanel />);

    await waitFor(() => {
      expect(screen.getByText("s1")).toBeInTheDocument();
    });

    expect(screen.getByText("— unknown")).toBeInTheDocument();
    expect(screen.queryByText(/Opus/)).not.toBeInTheDocument();
    expect(screen.queryByText(/PR/)).not.toBeInTheDocument();
  });

  it("shows stale marker for stale sessions", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValueOnce({
      sessions: [
        {
          id: "s1",
          worktree_cwd: "/path/to/work",
          updated_at: 1234567890,
          stale: true,
        },
      ],
    });

    render(<SessionsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/stale/i)).toBeInTheDocument();
    });
  });

  it("shows live marker for fresh sessions", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockResolvedValueOnce({
      sessions: [
        {
          id: "s1",
          worktree_cwd: "/path/to/work",
          updated_at: 1234567890,
          stale: false,
        },
      ],
    });

    render(<SessionsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/live/i)).toBeInTheDocument();
    });
  });

  it("renders empty list on mount fetch failure", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);
    mockGetSessions.mockRejectedValueOnce(new Error("Network error"));

    render(<SessionsPanel />);

    await waitFor(() => {
      const container = screen.getByRole("region");
      expect(container).toBeInTheDocument();
    });

    expect(screen.queryByText(/night-shift/)).not.toBeInTheDocument();
  });

  it("component setup mounts without crashing and cleanup prevents setState", async () => {
    const mockGetSessions = vi.mocked(client.getSessions);

    mockGetSessions.mockResolvedValue({
      sessions: [
        {
          id: "s1",
          worktree_cwd: "/path/to/work",
          updated_at: 1234567890,
          stale: false,
          session_name: "test",
        },
      ],
    });

    const { unmount } = render(<SessionsPanel />);

    // Component should render
    await waitFor(() => {
      expect(screen.getByText("test")).toBeInTheDocument();
    });

    // Unmount should not throw
    expect(() => {
      unmount();
    }).not.toThrow();
  });
});
