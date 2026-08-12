import { describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import type {
  BoardCard,
  BoardResponse,
  Context,
  Limits,
  RateWindow,
  RepoEntry,
} from "../api/types";
import type { PartyMember } from "../board/party";
import TopBar, { type TopBarProps, type TrailOrientation } from "./TopBar";

// `controlsOpen`/`filtersOpen` are App-owned, so TopBar is a fully
// controlled component — it renders the "Controls ▾"/"Filters ▾" buttons
// but doesn't own whether either is open. Every test in this file needs
// both pairs; this harness reproduces App's own `useState`s + toggle
// callbacks locally so tests that click a toggle and expect its region to
// actually show/hide (or its `aria-expanded` to flip) keep working without
// each test hand-rolling its own state. `controlsOpen` defaults false here
// (this file's own long-standing convention, covering the collapsed case
// most tests below need) — independent of App.tsx's own default, which is
// `true` (Task 3: the board looks unchanged on load).
function StatefulTopBar(
  props: Omit<
    TopBarProps,
    "controlsOpen" | "onToggleControls" | "filtersOpen" | "onToggleFilters"
  >
) {
  const [controlsOpen, setControlsOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(true);
  return (
    <TopBar
      {...props}
      controlsOpen={controlsOpen}
      onToggleControls={() => setControlsOpen((open) => !open)}
      filtersOpen={filtersOpen}
      onToggleFilters={() => setFiltersOpen((open) => !open)}
    />
  );
}

function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

function card(overrides: Partial<BoardCard> & { id: string }): BoardCard {
  return {
    title: `Title ${overrides.id}`,
    status: "planned",
    stage: null,
    complexity: null,
    priority: null,
    sprint: null,
    parent: null,
    depends_on: [],
    order: 10,
    budget: { estimate: null, actual: 0 },
    is_epic: false,
    ready: true,
    rollup: null,
    created: "",
    updated: "",
    checklist: [],
    labels: [],
    body: "",
    links: [],
    pr: null,
    ...overrides,
  };
}

function partyMember(
  overrides: Partial<PartyMember["session"]> & { id: string },
  quest: Partial<Pick<PartyMember, "questCardId" | "questTitle">> = {}
): PartyMember {
  return {
    session: {
      worktree_cwd: "/w",
      updated_at: 1,
      stale: false,
      ...overrides,
    },
    questCardId: null,
    questTitle: null,
    ...quest,
  };
}

function baseProps() {
  return {
    context: null as Context | null,
    limits: null as Limits,
    quarantinedCount: 0,
    showArchive: false,
    onToggleArchive: () => {},
    onRefresh: () => {},
    refreshing: false,
    mutate: makeMutate(),
    inFlight: false,
    cards: [] as BoardCard[],
    party: [] as PartyMember[],
    lastRefreshedAt: null as Date | null,
    onOpenParty: () => {},
    repos: [] as RepoEntry[],
    activeRoot: null as string | null,
    onSelectRepo: () => {},
    branches: [] as string[],
    activeBranch: null as string | null,
    onSelectBranch: () => {},
    // WF-086: Board|Atlas view toggle — every existing test gets a stable
    // default (board view, no-op handler) via this shared fixture so only
    // the toggle's own describe block below needs to care about it.
    view: "board" as "board" | "atlas",
    onSelectView: () => {},
    // WF-091: Epic Atlas toggle defaults — every existing test gets a
    // stable no-op fixture (matching `view`'s own default above) via this
    // shared helper; only the atlas-controls describe block below cares
    // about these.
    showNames: true,
    onToggleNames: () => {},
    hideVanquished: true,
    onToggleVanquished: () => {},
    orientation: "across" as TrailOrientation,
    onToggleOrientation: () => {},
  };
}

// WF-085: threshold/Labels…/Refresh/Abandoned/Clear… now live behind the
// mobile "Controls ▾" toggle, collapsed by default (see the describe block
// below). Existing tests that reach into that group have to open it first —
// this helper is that one step, shared everywhere it's needed.
function openControls() {
  fireEvent.click(screen.getByRole("button", { name: /^controls/i }));
}

describe("<TopBar/>", () => {
  // Task 5: last-refreshed moved out of the Controls group and renders as
  // a `.topbar__pill` note-badge beside the Short/Long Rest pills instead
  // of its own dedicated `.topbar__updated` class.
  it("shows the last-refreshed time as a '.topbar__pill' badge when set", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        lastRefreshedAt={new Date(2026, 0, 1, 14, 32)}
      />
    );

    const updated = screen.getByText("updated 14:32");
    expect(updated).toBeInTheDocument();
    expect(updated).toHaveClass("topbar__pill");
    // The repo name that used to share this line is gone — it now lives only
    // in the repo selector below, so no "name · updated …" middot here.
    expect(updated.textContent).not.toMatch(/·/);
  });

  it("renders no last-updated text when lastRefreshedAt is null", () => {
    render(<StatefulTopBar {...baseProps()} lastRefreshedAt={null} />);

    expect(screen.queryByText(/updated/i)).toBeNull();
  });

  it("renders the gold-total pill summed from budget.actual across cards", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        cards={[card({ id: "WF-1", budget: { estimate: null, actual: 500 } }), card({ id: "WF-2", budget: { estimate: null, actual: 250 } })]}
      />
    );

    expect(screen.getByText("750")).toBeInTheDocument();
  });

  it("renders the N / M vanquished pill from done-count over total", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        cards={[
          card({ id: "WF-1", status: "done" }),
          card({ id: "WF-2", status: "done" }),
          card({ id: "WF-3", status: "in-flight" }),
        ]}
      />
    );

    expect(screen.getByText("2 / 3 vanquished")).toBeInTheDocument();
  });

  it("the fleet-health pill's questing count includes only live (non-stale) party members", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        party={[
          partyMember({ id: "s1", stale: false }),
          partyMember({ id: "s2", stale: false }),
          partyMember({ id: "s3", stale: true }),
        ]}
      />
    );

    expect(screen.getByText(/2 questing/)).toBeInTheDocument();
  });

  it("clicking the fleet-health pill calls onOpenParty", () => {
    const onOpenParty = vi.fn();
    render(
      <StatefulTopBar
        {...baseProps()}
        party={[partyMember({ id: "s1" })]}
        onOpenParty={onOpenParty}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /questing/i }));
    expect(onOpenParty).toHaveBeenCalledTimes(1);
  });

  // WF-042: the old dedicated launching-session readout (context.model,
  // context.pr, the single "ctx NN%" value) is gone from this bar — those
  // facts now live per-agent on the Party's hero cards instead.
  it("no longer renders context.model, context.pr, or a single ctx% value", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        context={{
          pct: 42,
          threshold: 80,
          model: "Opus",
          pr: { number: 7, review_state: "approved" },
        }}
      />
    );

    expect(screen.queryByText("Opus")).not.toBeInTheDocument();
    expect(screen.queryByText(/PR #7/)).not.toBeInTheDocument();
    expect(document.querySelector(".topbar__ctx-value")).toBeNull();
    expect(document.querySelector(".topbar__ctx-note")).toBeNull();
  });

  it("renders the fleet-health line with top ctx and near-threshold segments derived from live party sessions", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        context={{ pct: null, threshold: 80 }}
        party={[
          partyMember({ id: "s1", pct: 86 }),
          partyMember({ id: "s2", pct: 82 }),
          partyMember({ id: "s3", pct: 10 }),
        ]}
      />
    );

    expect(
      screen.getByText(/3 questing · top ctx 86% · 2 near threshold/)
    ).toBeInTheDocument();
  });

  it("omits the top-ctx and near-threshold segments gracefully when there's no pct data (never NaN/null)", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        context={{ pct: null, threshold: 80 }}
        party={[partyMember({ id: "s1" }), partyMember({ id: "s2" })]}
      />
    );

    const pill = screen.getByRole("button", { name: /questing/i });
    expect(pill).toHaveTextContent(/^\D*2 questing\D*$/);
    expect(pill.textContent).not.toMatch(/null|NaN|undefined/);
  });

  it("keeps the threshold control, relabeled as the fleet's default", () => {
    render(<StatefulTopBar {...baseProps()} context={{ pct: null, threshold: 65 }} />);

    expect(screen.getByLabelText("Threshold")).toHaveValue("65");
    expect(screen.getByText(/last orders/i)).toBeInTheDocument();
  });

  it("renders no Sessions toggle — the old sessions dropdown retired, the fleet-health pill replaces it", () => {
    render(<StatefulTopBar {...baseProps()} />);
    expect(
      screen.queryByRole("button", { name: /^sessions$/i })
    ).not.toBeInTheDocument();
  });

  // WF-076 renamed the abandoned-cards lane Archive → Abandoned but the
  // toggle's rendered label was missed — nothing asserted on it, so the
  // mismatch slipped through review. Internal names (`showArchive`,
  // `onToggleArchive`, `topbar__archive-toggle`) stay as-is; only the
  // user-visible text must read "Abandoned".
  it("renders the abandoned-lane toggle labelled 'Abandoned'", () => {
    render(<StatefulTopBar {...baseProps()} />);

    const toggle = document.querySelector(".topbar__archive-toggle");
    expect(toggle).not.toBeNull();
    expect(toggle!.textContent).toMatch(/Abandoned/);
    expect(toggle!.textContent).not.toMatch(/Archive/);
  });

  it("renders no repo selector when no boards are discoverable", () => {
    render(<StatefulTopBar {...baseProps()} repos={[]} />);
    expect(screen.queryByLabelText("Repo")).not.toBeInTheDocument();
  });

  it("renders the repo selector with every discovered repo as an option", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        repos={[
          { label: "repo-a", root: "/a", current: true, has_board: true, live_sessions: 0 },
          { label: "repo-b", root: "/b", current: false, has_board: true, live_sessions: 0 },
        ]}
        activeRoot="/a"
      />
    );

    const select = screen.getByLabelText("Repo") as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe("/a");
    expect(screen.getByRole("option", { name: "repo-a" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "repo-b" })).toBeInTheDocument();
  });

  it("selecting a different repo calls onSelectRepo with its root", () => {
    const onSelectRepo = vi.fn();
    render(
      <StatefulTopBar
        {...baseProps()}
        repos={[
          { label: "repo-a", root: "/a", current: true, has_board: true, live_sessions: 0 },
          { label: "repo-b", root: "/b", current: false, has_board: true, live_sessions: 0 },
        ]}
        activeRoot="/a"
        onSelectRepo={onSelectRepo}
      />
    );

    fireEvent.change(screen.getByLabelText("Repo"), {
      target: { value: "/b" },
    });

    expect(onSelectRepo).toHaveBeenCalledWith("/b");
  });

  it("renders no branch filter when there are no distinct branches", () => {
    render(<StatefulTopBar {...baseProps()} branches={[]} />);
    expect(screen.queryByLabelText("Branch")).not.toBeInTheDocument();
  });

  it("renders the branch filter with every distinct branch as an option", () => {
    render(
      <StatefulTopBar {...baseProps()} branches={["feat/a", "feat/b"]} activeBranch="feat/a" />
    );

    const select = screen.getByLabelText("Branch") as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe("feat/a");
    expect(screen.getByRole("option", { name: "feat/a" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "feat/b" })).toBeInTheDocument();
  });

  it("selecting a different branch calls onSelectBranch with its name", () => {
    const onSelectBranch = vi.fn();
    render(
      <StatefulTopBar
        {...baseProps()}
        branches={["feat/a", "feat/b"]}
        activeBranch="feat/a"
        onSelectBranch={onSelectBranch}
      />
    );

    fireEvent.change(screen.getByLabelText("Branch"), {
      target: { value: "feat/b" },
    });

    expect(onSelectBranch).toHaveBeenCalledWith("feat/b");
  });

  it("renders the Short Rest pill with the rounded 5h usage and a '5h window' tooltip", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        limits={{
          five_hour: { used_percentage: 28.000000000000004 } as RateWindow,
        }}
      />
    );

    const pill = screen.getByText(/Short Rest/);
    expect(pill).toHaveTextContent("Short Rest 28%");
    expect(pill).toHaveAttribute("title", "5h window");
  });

  it("renders the Long Rest pill with the rounded 7d usage and a '7d window' tooltip", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        limits={{
          seven_day: { used_percentage: 63.4 } as RateWindow,
        }}
      />
    );

    const pill = screen.getByText(/Long Rest/);
    expect(pill).toHaveTextContent("Long Rest 63%");
    expect(pill).toHaveAttribute("title", "7d window");
  });

  it("omits the Short Rest / Long Rest pills when their window is absent from limits", () => {
    render(<StatefulTopBar {...baseProps()} limits={{}} />);

    expect(screen.queryByText(/Short Rest/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Long Rest/)).not.toBeInTheDocument();
  });

  // Task 7: Clear-data control — gated entirely on the `onClear` prop so
  // App.tsx can withhold it when no repo is selected (see App.tsx's
  // `selectedRepo ? () => setClearOpen(true) : undefined`).
  it("renders no Clear button when onClear is not provided", () => {
    render(<StatefulTopBar {...baseProps()} />);
    expect(
      screen.queryByRole("button", { name: /clear/i })
    ).not.toBeInTheDocument();
  });

  it("renders a Clear button when onClear is provided, and clicking it calls onClear", () => {
    const onClear = vi.fn();
    render(<StatefulTopBar {...baseProps()} onClear={onClear} />);

    // WF-085: Clear… lives in the collapsed-by-default Controls group now
    // (WF-090: as its LAST/rightmost child — see the ordering test below).
    openControls();
    const button = screen.getByRole("button", { name: /clear/i });
    expect(button).toBeInTheDocument();
    fireEvent.click(button);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  // WF-090: Clear… is the one destructive action in this group — it now
  // renders LAST (rightmost, both on desktop's plain-DOM-order flow and
  // mobile's flex-wrap row — see styles.css), separated from the
  // constructive controls rather than leading them.
  // WF-090 follow-up: Labels… moved from BEFORE the threshold control to
  // AFTER it, so it groups with the Refresh/Abandoned/Clear… action row
  // instead of sitting up top beside Last Orders — Clear… itself stays
  // last (see the earlier WF-090 move).
  it("groups Labels… with the action-row buttons (before Refresh), keeping Clear… last", () => {
    render(<StatefulTopBar {...baseProps()} onClear={() => {}} />);
    openControls();

    const group = document.getElementById("topbar-controls-group")!;
    const buttonTexts = Array.from(group.querySelectorAll("button")).map(
      (b) => b.textContent ?? ""
    );
    const labelsIndex = buttonTexts.findIndex((t) => /^labels/i.test(t));
    const refreshIndex = buttonTexts.findIndex((t) => /^refresh/i.test(t));
    const clearIndex = buttonTexts.findIndex((t) => /^clear/i.test(t));

    expect(labelsIndex).toBeGreaterThan(-1);
    expect(labelsIndex).toBeLessThan(refreshIndex);
    expect(clearIndex).toBe(buttonTexts.length - 1);
  });

  // Task 10: "＋ New card" — TopBar owns the dialog's open state itself
  // (no App-level prop needed) and hands it TopBar's own `mutate` prop.
  it("renders no New card dialog until the New card button is clicked", () => {
    render(<StatefulTopBar {...baseProps()} />);
    expect(screen.getByRole("button", { name: /new card/i })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /new card/i })).not.toBeInTheDocument();
  });

  it("clicking the New card button opens NewCardDialog", () => {
    render(<StatefulTopBar {...baseProps()} />);

    fireEvent.click(screen.getByRole("button", { name: /new card/i }));

    expect(screen.getByRole("dialog", { name: /new card/i })).toBeInTheDocument();
  });

  // Task 2: "＋ New card" is icon-only now — the visible label text is
  // dropped, but `aria-label`/`title="New card"` keep it resolvable by name
  // exactly like the old "＋ New card" text button was.
  it("renders the New card button icon-only, still accessible by name", () => {
    render(<StatefulTopBar {...baseProps()} />);
    const button = screen.getByRole("button", { name: /new card/i });
    expect(button).toHaveTextContent("＋");
    expect(button.textContent).not.toMatch(/new card/i);
    expect(button).toHaveAttribute("title", "New card");
  });

  // Task 10 (F10, WF-067): the Labels settings control — TopBar owns the
  // dialog's open state itself, same pattern as "＋ New card" above.
  it("renders no Label colors dialog until the Labels settings button is clicked", () => {
    render(<StatefulTopBar {...baseProps()} />);
    // WF-085: Labels… lives in the collapsed-by-default Controls group now.
    openControls();
    expect(screen.getByRole("button", { name: /labels/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: /label colors/i })
    ).not.toBeInTheDocument();
  });

  it("clicking the Labels settings button opens LabelSettingsDialog with the board's distinct labels", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        cards={[
          card({ id: "WF-1", labels: ["policy"] }),
          card({ id: "WF-2", labels: ["architecture"] }),
        ]}
      />
    );

    openControls();
    fireEvent.click(screen.getByRole("button", { name: /labels/i }));

    expect(
      screen.getByRole("dialog", { name: /label colors/i })
    ).toBeInTheDocument();
    expect(screen.getByText("policy")).toBeInTheDocument();
    expect(screen.getByText("architecture")).toBeInTheDocument();
  });
});

// WF-085/Task 2/3: "Controls ▾" collapses threshold/Labels…/Refresh/
// Abandoned/Clear… — its OWN region now (`#topbar-controls-group`), split
// from the old shared toggle that also drove <FilterBar/>. The collapse
// itself is implemented with the native `hidden` attribute (see TopBar.tsx),
// which jsdom's own accessibility-tree logic honours regardless of whether
// any stylesheet is loaded — `getByRole` excludes descendants of a `hidden`
// ancestor by default, and jest-dom's `toBeVisible()` checks
// `hasAttribute('hidden')` directly. That's what lets these tests verify
// real show/hide behaviour without styles.css ever being imported here;
// Task 3: styles.css now lets `[hidden]` hide this group on EVERY viewport,
// not just ≤720px (see the CSS content assertions further down and
// styles.css itself).
describe("<TopBar/> mobile Controls toggle (WF-085)", () => {
  it("collapses the secondary controls by default, hiding them from the accessibility tree", () => {
    render(<StatefulTopBar {...baseProps()} onClear={() => {}} />);

    const toggle = screen.getByRole("button", { name: /^controls/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Task 2: "Controls ▾" now drives ONLY TopBar's own group — the
    // separate <FilterBar/> App.tsx renders as a sibling is driven by its
    // own independent "Filters ▾" toggle instead (see the describe block
    // below).
    expect(toggle).toHaveAttribute("aria-controls", "topbar-controls-group");

    expect(screen.queryByRole("button", { name: /^clear/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^labels/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^refresh/i })).not.toBeInTheDocument();

    const group = document.getElementById("topbar-controls-group");
    expect(group).not.toBeNull();
    expect(group).not.toBeVisible();
  });

  it("clicking the toggle expands the group, flips aria-expanded, and surfaces every collapsed control", () => {
    render(<StatefulTopBar {...baseProps()} onClear={() => {}} />);

    const toggle = screen.getByRole("button", { name: /^controls/i });
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /^clear/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^labels/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^refresh/i })).toBeInTheDocument();
    expect(screen.getByText("Abandoned")).toBeInTheDocument();
    expect(document.getElementById("topbar-controls-group")).toBeVisible();
  });

  it("clicking the toggle a second time re-collapses the group", () => {
    render(<StatefulTopBar {...baseProps()} onClear={() => {}} />);

    const toggle = screen.getByRole("button", { name: /^controls/i });
    fireEvent.click(toggle);
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /^clear/i })).not.toBeInTheDocument();
    expect(document.getElementById("topbar-controls-group")).not.toBeVisible();
  });

  it("keeps repo · branch · ＋New card and the status glance pills outside the collapsed group, always accessible", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        repos={[{ label: "repo-a", root: "/a", current: true, has_board: true, live_sessions: 0 }]}
        activeRoot="/a"
        branches={["feat/a"]}
        activeBranch="feat/a"
        limits={{
          five_hour: { used_percentage: 28 } as RateWindow,
          seven_day: { used_percentage: 63 } as RateWindow,
        }}
      />
    );

    // Collapsed by default (no click) — these are still all reachable.
    expect(screen.getByLabelText("Repo")).toBeInTheDocument();
    expect(screen.getByLabelText("Branch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new card/i })).toBeInTheDocument();
    expect(screen.getByText(/Short Rest/)).toBeInTheDocument();
    expect(screen.getByText(/Long Rest/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /questing/i })).toBeInTheDocument();
    expect(screen.getByText(/vanquished/)).toBeInTheDocument();
  });
});

// Task 2: "Filters ▾" is its OWN independent toggle now (was folded into
// the shared "Controls ▾" toggle) — wired to `filter-bar` only, entirely
// separate from `topbar-controls-group`/`onToggleControls`.
describe("<TopBar/> Filters toggle (Task 2)", () => {
  it("wires aria-expanded to filtersOpen and aria-controls to filter-bar only", () => {
    render(<StatefulTopBar {...baseProps()} />);

    const toggle = screen.getByRole("button", { name: /^filters/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "filter-bar");
  });

  it("clicking the Filters toggle calls onToggleFilters and flips aria-expanded/the caret", () => {
    const onToggleFilters = vi.fn();
    const { rerender } = render(
      <TopBar
        {...baseProps()}
        controlsOpen={false}
        onToggleControls={() => {}}
        filtersOpen={true}
        onToggleFilters={onToggleFilters}
      />
    );

    const toggle = screen.getByRole("button", { name: /^filters/i });
    expect(toggle).toHaveTextContent("Filters ▴");
    fireEvent.click(toggle);
    expect(onToggleFilters).toHaveBeenCalledTimes(1);

    rerender(
      <TopBar
        {...baseProps()}
        controlsOpen={false}
        onToggleControls={() => {}}
        filtersOpen={false}
        onToggleFilters={onToggleFilters}
      />
    );
    expect(screen.getByRole("button", { name: /^filters/i })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    expect(screen.getByRole("button", { name: /^filters/i })).toHaveTextContent(
      "Filters ▾"
    );
  });

  it("toggling Filters never affects the Controls group (fully independent)", () => {
    render(<StatefulTopBar {...baseProps()} onClear={() => {}} />);

    // Controls starts collapsed (this file's StatefulTopBar default).
    expect(document.getElementById("topbar-controls-group")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /^filters/i }));
    // Filters flipped, Controls untouched.
    expect(document.getElementById("topbar-controls-group")).not.toBeVisible();
  });

  it("puts the toggle cluster in [Filters ▾] [Controls ▾] [＋] order", () => {
    const { container } = render(<StatefulTopBar {...baseProps()} />);
    const cluster = container.querySelector(".topbar__toggle-cluster")!;
    expect(cluster).not.toBeNull();
    const buttons = Array.from(cluster.querySelectorAll("button"));
    expect(buttons).toHaveLength(3);
    expect(buttons[0]).toHaveAccessibleName(/^filters/i);
    expect(buttons[1]).toHaveAccessibleName(/^controls/i);
    expect(buttons[2]).toHaveAccessibleName(/new card/i);
  });
});

// Task 4: `#topbar-controls-group` opens with a small dotted-line header +
// title, before ThresholdControl.
describe("<TopBar/> Controls group header (Task 4)", () => {
  it("renders a header with the group's eyebrow title before ThresholdControl", () => {
    render(<StatefulTopBar {...baseProps()} />);
    openControls();

    const group = document.getElementById("topbar-controls-group")!;
    const header = group.querySelector(".topbar__controls-header");
    expect(header).not.toBeNull();
    expect(header!.textContent).toBe("Provisions");

    const children = Array.from(group.children);
    const headerIndex = children.indexOf(header!);
    const thresholdIndex = children.findIndex((c) =>
      c.classList.contains("topbar__threshold")
    );
    expect(headerIndex).toBeGreaterThanOrEqual(0);
    expect(headerIndex).toBeLessThan(thresholdIndex);
  });
});

// WF-086: Board|Atlas view toggle. Role-B "T1 gold underline" tab pattern
// (same aria-pressed mechanics as CardDetailDrawer's `.card-drawer__viewtoggle`
// segmented tabs), but under its own `.topbar__view-toggle` class — this is
// a NEW selector, not a reuse of the drawer's, since the two toggles live in
// unrelated parts of the tree and shouldn't share a CSS identity by accident.
describe("<TopBar/> view toggle (WF-086)", () => {
  it("renders a Board button and an Atlas button", () => {
    render(<StatefulTopBar {...baseProps()} />);
    expect(screen.getByRole("button", { name: "Board" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Atlas" })).toBeInTheDocument();
  });

  it("marks the current view's button aria-pressed=true and the other false", () => {
    const { rerender } = render(<StatefulTopBar {...baseProps()} view="board" />);
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Atlas" })).toHaveAttribute("aria-pressed", "false");

    rerender(<StatefulTopBar {...baseProps()} view="atlas" />);
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Atlas" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switches to the other view when EITHER coin is clicked", () => {
    const onSelectView = vi.fn();
    const { rerender } = render(
      <StatefulTopBar {...baseProps()} view="board" onSelectView={onSelectView} />
    );
    // On the board, either coin takes you to the atlas — including the active
    // Board coin (no longer a dead click).
    fireEvent.click(screen.getByRole("button", { name: "Atlas" }));
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(onSelectView).toHaveBeenNthCalledWith(1, "atlas");
    expect(onSelectView).toHaveBeenNthCalledWith(2, "atlas");

    onSelectView.mockClear();
    rerender(<StatefulTopBar {...baseProps()} view="atlas" onSelectView={onSelectView} />);
    // On the atlas, either coin takes you back to the board.
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    fireEvent.click(screen.getByRole("button", { name: "Atlas" }));
    expect(onSelectView).toHaveBeenNthCalledWith(1, "board");
    expect(onSelectView).toHaveBeenNthCalledWith(2, "board");
  });

  it("puts both view-toggle circles inside the always-visible .topbar__identity, never in #topbar-controls-group", () => {
    const { container } = render(<StatefulTopBar {...baseProps()} />);
    const circles = container.querySelectorAll(".topbar__view-toggle-btn");
    expect(circles).toHaveLength(2);
    // Always-visible identity cluster — never behind the mobile "Controls ▾"
    // collapse.
    circles.forEach((c) => expect(c.closest(".topbar__identity")).not.toBeNull());
    expect(container.querySelector("#topbar-controls-group .topbar__view-toggle-btn")).toBeNull();
  });

  it("stacks both coins in the .topbar__view-toggle group ahead of the wordmark; identity sits before the repo selector", () => {
    const { container } = render(
      <StatefulTopBar {...baseProps()} repos={[{ root: "/r", label: "r", current: true, has_board: true, live_sessions: 0 }]} />
    );
    const identity = container.querySelector(".topbar__identity")!;
    const stack = identity.querySelector(".topbar__view-toggle")!;
    // Both coins live together in the stack (an overlapping pair, not flanking).
    expect(stack.querySelectorAll(".topbar__view-toggle-btn")).toHaveLength(2);
    // The stack comes before the wordmark within the identity cluster.
    const kids = Array.from(identity.children);
    const stackIndex = kids.indexOf(stack);
    const titleIndex = kids.findIndex((c) => c.tagName === "H1");
    expect(stackIndex).toBeGreaterThanOrEqual(0);
    expect(stackIndex).toBeLessThan(titleIndex);
    // The identity cluster itself still precedes the repo selector in the bar.
    const header = container.querySelector("header.topbar")!;
    const barKids = Array.from(header.children);
    const identityIndex = barKids.indexOf(identity);
    const repoIndex = barKids.findIndex((c) => c.classList.contains("topbar__repo-select"));
    expect(identityIndex).toBeGreaterThanOrEqual(0);
    expect(identityIndex).toBeLessThan(repoIndex);
  });
});

// WF-091: the Epic Atlas toolbar folded into the Controls group — three
// single toggle buttons, shown ONLY on `view === "atlas"` (the retired
// standalone `<AtlasToolbar>` used to render these, as three segmented
// two-button pairs, between the topbar and the chart). Lives inside
// `#topbar-controls-group`, so — like Labels…/Refresh/Abandoned/Clear… —
// these tests open the mobile Controls collapse first via `openControls()`.
describe("<TopBar/> Epic Atlas controls (WF-091)", () => {
  it("renders no atlas controls on the board view", () => {
    render(<StatefulTopBar {...baseProps()} view="board" />);
    openControls();
    expect(screen.queryByRole("button", { name: /quest names/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vanquished/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /across|down/i })).not.toBeInTheDocument();
  });

  it("renders the three atlas controls on the atlas view", () => {
    render(<StatefulTopBar {...baseProps()} view="atlas" />);
    openControls();
    expect(screen.getByRole("button", { name: /quest names/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /vanquished/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /across|down/i })).toBeInTheDocument();
  });

  it("Quest names button reflects showNames and calls onToggleNames with the flipped value", () => {
    const onToggleNames = vi.fn();
    const { rerender } = render(
      <StatefulTopBar {...baseProps()} view="atlas" showNames onToggleNames={onToggleNames} />
    );
    openControls();
    const btn = screen.getByRole("button", { name: /quest names/i });
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(btn).toHaveTextContent(/on/i);
    fireEvent.click(btn);
    expect(onToggleNames).toHaveBeenCalledWith(false);

    rerender(
      <StatefulTopBar {...baseProps()} view="atlas" showNames={false} onToggleNames={onToggleNames} />
    );
    const offBtn = screen.getByRole("button", { name: /quest names/i });
    expect(offBtn).toHaveAttribute("aria-pressed", "false");
    expect(offBtn).toHaveTextContent(/off/i);
  });

  it("Vanquished button reflects hideVanquished (default hidden) and calls onToggleVanquished with the flipped value", () => {
    const onToggleVanquished = vi.fn();
    const { rerender } = render(
      <StatefulTopBar
        {...baseProps()}
        view="atlas"
        hideVanquished
        onToggleVanquished={onToggleVanquished}
      />
    );
    openControls();
    const btn = screen.getByRole("button", { name: /vanquished/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(btn).toHaveTextContent(/hidden/i);
    fireEvent.click(btn);
    expect(onToggleVanquished).toHaveBeenCalledWith(false);

    rerender(
      <StatefulTopBar
        {...baseProps()}
        view="atlas"
        hideVanquished={false}
        onToggleVanquished={onToggleVanquished}
      />
    );
    const shownBtn = screen.getByRole("button", { name: /vanquished/i });
    expect(shownBtn).toHaveAttribute("aria-pressed", "true");
    expect(shownBtn).toHaveTextContent(/shown/i);
  });

  it("Direction button reflects orientation and calls onToggleOrientation with the flipped value", () => {
    const onToggleOrientation = vi.fn();
    const { rerender } = render(
      <StatefulTopBar
        {...baseProps()}
        view="atlas"
        orientation="across"
        onToggleOrientation={onToggleOrientation}
      />
    );
    openControls();
    const btn = screen.getByRole("button", { name: /across/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    expect(onToggleOrientation).toHaveBeenCalledWith("down");

    rerender(
      <StatefulTopBar
        {...baseProps()}
        view="atlas"
        orientation="down"
        onToggleOrientation={onToggleOrientation}
      />
    );
    const downBtn = screen.getByRole("button", { name: /down/i });
    expect(downBtn).toHaveAttribute("aria-pressed", "true");
  });
});

// WF-085b Build item 1: the repo/branch <select>s truncate a long value
// with an ellipsis instead of wrapping, on every viewport. styles.css is
// never imported by these component tests (only src/main.tsx imports it —
// see the other frontend test files), so there is no computed-style
// signal to assert on from jsdom; instead this reads the real stylesheet
// source and asserts the specific truncation declarations are present.
// This is a regression guard against someone dropping the rule later, not
// a substitute for visual QA.
//
// WF-097 follow-up: RepoSelector.tsx/BranchFilter.tsx's `<select>`s now
// render via the shared `<Select/>` primitive (`.qb-select`) — the
// truncation declarations moved there (every `<Select/>` gets them, not
// just these two), so the guard now reads `.qb-select`'s own rule rather
// than `.topbar__repo-select select`/`.topbar__branch-select select`
// (which keep only their own genuine overrides — a transparent background,
// plus the branch select's own wobble variant — nothing duplicated).
describe("topbar repo/branch select truncation styling (WF-085b)", () => {
  const css = readFileSync(path.resolve(process.cwd(), "src/styles.css"), "utf-8");

  function ruleBodyFor(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
    expect(match, `expected a CSS rule for ${selector}`).not.toBeNull();
    return match![1];
  }

  it("truncates every <Select/>-rendered control with an ellipsis instead of wrapping", () => {
    const body = ruleBodyFor(".qb-select");
    expect(body).toMatch(/overflow:\s*hidden/);
    expect(body).toMatch(/text-overflow:\s*ellipsis/);
    expect(body).toMatch(/white-space:\s*nowrap/);
    expect(body).toMatch(/min-width:\s*0/);
  });

  it("still renders the repo <select> with its own transparent-background override", () => {
    expect(ruleBodyFor(".topbar__repo-select select")).toMatch(
      /background:\s*transparent/
    );
  });

  it("still renders the branch <select> with its own transparent-background override", () => {
    expect(ruleBodyFor(".topbar__branch-select select")).toMatch(
      /background:\s*transparent/
    );
  });

  it("lets the repo/branch chip wrappers shrink below their content width so the ellipsis can engage", () => {
    expect(ruleBodyFor(".topbar__repo-select")).toMatch(/min-width:\s*0/);
    expect(ruleBodyFor(".topbar__branch-select")).toMatch(/min-width:\s*0/);
  });
});
