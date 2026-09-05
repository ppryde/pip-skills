/** The Chronicle on TopBar: a third coin in the view switcher when the
 * plugin is installed, and a page-specific bar while it shows — Sync where
 * ＋ New card sits, no Controls group, no branch filter. */
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
    branches: ["main"],
    activeBranch: null,
    onSelectBranch: () => {},
    controlsOpen: true,
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

describe("TopBar Chronicle coin", () => {
  it("is absent unless the plugin is available, leaving a two-coin row", () => {
    const { container } = render(<TopBar {...props()} />);
    expect(screen.queryByRole("button", { name: "Chronicle" })).not.toBeInTheDocument();
    expect(container.querySelector(".topbar__view-toggle")).toHaveAttribute("data-count", "2");
  });

  it("is a third coin that selects the chronicle view and is pressed while it shows", () => {
    const onSelectView = vi.fn();
    const { container, rerender } = render(<TopBar {...props({ chronicleAvailable: true, onSelectView })} />);
    const coin = screen.getByRole("button", { name: "Chronicle" });
    expect(coin).toHaveClass("topbar__view-toggle-btn");
    expect(container.querySelector(".topbar__view-toggle")).toHaveAttribute("data-count", "3");
    expect(coin).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(coin);
    expect(onSelectView).toHaveBeenCalledWith("chronicle");

    rerender(<TopBar {...props({ chronicleAvailable: true, onSelectView, view: "chronicle" })} />);
    expect(screen.getByRole("button", { name: "Chronicle" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Atlas" })).toHaveAttribute("aria-pressed", "false");
    // Any coin selects its own page directly.
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(onSelectView).toHaveBeenLastCalledWith("board");
  });
});

describe("TopBar on the Chronicle page", () => {
  const repos = [{ root: "/r", label: "r", current: true, has_board: true, live_sessions: 0 }];

  it("swaps ＋ New card for Sync and drops Controls; repo and branch selectors stay", () => {
    const onChronicleSync = vi.fn();
    const { container } = render(
      <TopBar {...props({ chronicleAvailable: true, view: "chronicle", onChronicleSync, repos })} />
    );
    const sync = screen.getByRole("button", { name: "Sync" });
    fireEvent.click(sync);
    expect(onChronicleSync).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "New card" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Controls/ })).not.toBeInTheDocument();
    expect(container.querySelector("#topbar-controls-group")).toHaveAttribute("hidden");
    // What stays: Filters ▾ (it reveals the Chronicle's time window), and the
    // repo + branch selectors, which drive the Chronicle's scope directly.
    expect(screen.getByRole("button", { name: /^Filters/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Repo" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Branch" })).toBeInTheDocument();
  });

  it("offers All repos in the repo selector only on the Chronicle page", () => {
    const onSelect = vi.fn();
    const allRepos = { selected: false, onSelect };
    const { rerender } = render(
      <TopBar {...props({ chronicleAvailable: true, view: "chronicle", repos, chronicleAllRepos: allRepos })} />
    );
    const repo = screen.getByRole("combobox", { name: "Repo" });
    expect(screen.getByRole("option", { name: "All repos" })).toBeInTheDocument();
    fireEvent.change(repo, { target: { value: " all" } });
    expect(onSelect).toHaveBeenCalledWith(true);

    rerender(
      <TopBar {...props({ chronicleAvailable: true, view: "chronicle", repos, chronicleAllRepos: { ...allRepos, selected: true } })} />
    );
    expect(screen.getByRole("combobox", { name: "Repo" })).toHaveValue(" all");

    rerender(<TopBar {...props({ chronicleAvailable: true, view: "board", repos, chronicleAllRepos: allRepos })} />);
    expect(screen.queryByRole("option", { name: "All repos" })).not.toBeInTheDocument();
  });

  it("shows Syncing… and disables the button while a sync runs", () => {
    render(<TopBar {...props({ chronicleAvailable: true, view: "chronicle", onChronicleSync: () => {}, chronicleSyncing: true })} />);
    expect(screen.getByRole("button", { name: "Syncing…" })).toBeDisabled();
  });

  it("keeps the board's controls on the other pages", () => {
    const { container } = render(<TopBar {...props({ chronicleAvailable: true, view: "board" })} />);
    expect(screen.getByRole("button", { name: "New card" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Controls/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
    expect(container.querySelector("#topbar-controls-group")).not.toHaveAttribute("hidden");
    expect(container.querySelector(".topbar__branch-select")).not.toBeNull();
  });
});
