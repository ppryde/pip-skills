/** The Chronicle nav entry on TopBar: present only when the plugin is
 * installed, pressed while the page shows, and the Board coin stays in
 * front meanwhile (the two-coin stack never shows two "back" coins). */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import TopBar from "../TopBar";
import type { TopBarProps } from "../TopBar";

function props(overrides: Partial<TopBarProps> = {}): TopBarProps {
  return {
    context: null,
    limits: null,
    quarantinedCount: 0,
    showArchive: true,
    onToggleArchive: () => {},
    onRefresh: () => {},
    refreshing: false,
    mutate: vi.fn() as unknown as TopBarProps["mutate"],
    inFlight: false,
    cards: [],
    party: [],
    lastRefreshedAt: null,
    onOpenParty: () => {},
    repos: [],
    activeRoot: null,
    onSelectRepo: () => {},
    branches: [],
    activeBranch: null,
    onSelectBranch: () => {},
    controlsOpen: false,
    onToggleControls: () => {},
    filtersOpen: false,
    onToggleFilters: () => {},
    view: "board",
    onSelectView: () => {},
    showNames: true,
    onToggleNames: () => {},
    hideVanquished: true,
    onToggleVanquished: () => {},
    ...overrides,
  };
}

describe("TopBar Chronicle entry", () => {
  it("is absent unless the plugin is available", () => {
    render(<TopBar {...props()} />);
    expect(screen.queryByRole("button", { name: /chronicle/i })).not.toBeInTheDocument();
  });

  it("selects the chronicle view and toggles back to the board", () => {
    const onSelectView = vi.fn();
    const { rerender } = render(<TopBar {...props({ chronicleAvailable: true, onSelectView })} />);
    const btn = screen.getByRole("button", { name: /chronicle/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    expect(onSelectView).toHaveBeenCalledWith("chronicle");

    rerender(<TopBar {...props({ chronicleAvailable: true, onSelectView, view: "chronicle" })} />);
    expect(screen.getByRole("button", { name: /chronicle/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Atlas" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: /chronicle/i }));
    expect(onSelectView).toHaveBeenLastCalledWith("board");
  });
});
