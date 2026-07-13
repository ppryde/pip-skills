import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { BoardResponse, Context, Limits } from "../api/types";
import TopBar from "./TopBar";

function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

function baseProps() {
  return {
    projectName: "acme",
    context: null as Context | null,
    limits: null as Limits,
    quarantinedCount: 0,
    showArchive: false,
    onToggleArchive: () => {},
    onRefresh: () => {},
    refreshing: false,
    mutate: makeMutate(),
    inFlight: false,
  };
}

describe("<TopBar/>", () => {
  it("renders 'as of last refresh' as visible text next to the ctx% display", () => {
    render(<TopBar {...baseProps()} context={{ pct: 42, threshold: 80 }} />);

    expect(screen.getByText(/as of last refresh/i)).toBeVisible();
  });

  it("renders a sessions toggle button that shows/hides the panel", () => {
    render(<TopBar {...baseProps()} />);

    // The sessions button should be present
    const sessionsButton = screen.getByRole("button", { name: /sessions/i });
    expect(sessionsButton).toBeInTheDocument();

    // Initially, the panel should not be visible
    expect(screen.queryByRole("region", { name: /active sessions/i })).not.toBeInTheDocument();

    // Click the button to show the panel
    fireEvent.click(sessionsButton);

    // Now the panel should be visible
    expect(screen.getByRole("region", { name: /active sessions/i })).toBeInTheDocument();

    // Click again to hide
    fireEvent.click(sessionsButton);

    // Panel should be hidden again
    expect(screen.queryByRole("region", { name: /active sessions/i })).not.toBeInTheDocument();
  });
});
