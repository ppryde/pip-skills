/** The Almoner on TopBar: a fourth coin in the view switcher when the plugin
 * is installed, and the board-only controls standing down while it shows.
 *
 * The slot assertions below are the point of this file. The coin row used to
 * place its coins with a hand-written `:nth-child` list and size itself from a
 * `data-count` list, both of which stopped at three — so the Almoner's coin
 * was given no slot, sat at the row's origin behind Board, and covered the
 * guild wordmark. Nothing failed, because nothing asked. */
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
    accounts: [],
    activeAccount: null,
    onSelectAccount: () => {},
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

/** The inline slot index a coin was given. `null` when it was given none —
 * which is the failure this file exists to catch. */
function slotOf(el: Element): string | null {
  return (el as HTMLElement).style.getPropertyValue("--slot") || null;
}

describe("TopBar Almoner coin", () => {
  it("is absent unless the plugin is available", () => {
    render(<TopBar {...props()} />);
    expect(screen.queryByRole("button", { name: "Almoner" })).not.toBeInTheDocument();
  });

  it("is a fourth coin that selects the almoner view and is pressed while it shows", () => {
    const onSelectView = vi.fn();
    const { container, rerender } = render(
      <TopBar {...props({ chronicleAvailable: true, almonerAvailable: true, onSelectView })} />
    );
    const coin = screen.getByRole("button", { name: "Almoner" });
    expect(coin).toHaveClass("topbar__view-toggle-btn");
    expect(container.querySelector(".topbar__view-toggle")).toHaveAttribute("data-count", "4");

    fireEvent.click(coin);
    expect(onSelectView).toHaveBeenCalledWith("almoner");

    rerender(
      <TopBar {...props({ chronicleAvailable: true, almonerAvailable: true, onSelectView, view: "almoner" })} />
    );
    expect(screen.getByRole("button", { name: "Almoner" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-pressed", "false");
  });

  it("gives EVERY coin its own slot, so none can sit on the wordmark", () => {
    const { container } = render(
      <TopBar {...props({ chronicleAvailable: true, almonerAvailable: true })} />
    );
    const coins = [...container.querySelectorAll(".topbar__view-toggle-btn")];
    expect(coins).toHaveLength(4);

    const slots = coins.map(slotOf);
    expect(slots).toEqual(["0", "1", "2", "3"]);
    // Distinct is the property that actually matters: two coins sharing a
    // slot is the bug, whatever the numbers happen to be.
    expect(new Set(slots).size).toBe(coins.length);
  });

  it("tells the row how many coins to make room for, at every count", () => {
    // The row's width is computed from this. When it lagged behind the real
    // count the last coin overflowed the row and landed on the title.
    for (const [opts, count] of [
      [{}, "2"],
      [{ chronicleAvailable: true }, "3"],
      [{ almonerAvailable: true }, "3"],
      [{ chronicleAvailable: true, almonerAvailable: true }, "4"],
    ] as [Partial<TopBarProps>, string][]) {
      const { container } = render(<TopBar {...props(opts)} />);
      const row = container.querySelector(".topbar__view-toggle") as HTMLElement;
      expect(row).toHaveAttribute("data-count", count);
      expect(row.style.getPropertyValue("--coin-count")).toBe(count);
    }
  });

  it("names the page you are on, rather than the guild on every page", () => {
    // The Chronicle has no heading of its own anywhere, so before this the
    // only way to tell which page you were looking at was to recognise its
    // contents. The board keeps the guild wordmark because there it IS the
    // page's name.
    for (const [view, title] of [
      ["board", "Adventurers\u2019 Guild Board"],
      ["atlas", "Epic Atlas"],
      ["chronicle", "Chronicle"],
      ["almoner", "Almoner"],
    ] as [TopBarProps["view"], string][]) {
      const { container } = render(
        <TopBar {...props({ chronicleAvailable: true, almonerAvailable: true, view })} />
      );
      expect(container.querySelector("h1")).toHaveTextContent(title);
    }
  });

  it("keeps the wordmark a sibling of the coin row, never inside it", () => {
    // They share `.topbar__identity`; the row reserves its own width and the
    // heading follows it in flow. A heading nested in the row would overlap
    // again no matter what the widths said.
    const { container } = render(<TopBar {...props({ almonerAvailable: true })} />);
    const identity = container.querySelector(".topbar__identity")!;
    expect(identity.querySelector(".topbar__view-toggle")).toBeInTheDocument();
    expect(identity.querySelector("h1")).toBeInTheDocument();
    expect(identity.querySelector(".topbar__view-toggle h1")).toBeNull();
  });
});
