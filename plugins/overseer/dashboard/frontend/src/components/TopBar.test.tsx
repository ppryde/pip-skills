import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
});
