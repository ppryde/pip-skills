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
import TopBar, { type TopBarProps } from "./TopBar";

// WF-085b: `controlsOpen` moved from TopBar-local state up to App.tsx, so
// TopBar is now a fully controlled component — it renders the "Controls ▾"
// button/group but doesn't own whether they're open. Every test in this
// file needs a `controlsOpen`/`onToggleControls` pair; this harness
// reproduces App's own `useState` + toggle callback locally so tests that
// click the toggle and expect the group to actually show/hide keep working
// without each test hand-rolling its own state.
function StatefulTopBar(
  props: Omit<TopBarProps, "controlsOpen" | "onToggleControls">
) {
  const [controlsOpen, setControlsOpen] = useState(false);
  return (
    <TopBar
      {...props}
      controlsOpen={controlsOpen}
      onToggleControls={() => setControlsOpen((open) => !open)}
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
  };
}

// WF-085: threshold/Clear…/Labels…/Refresh/Abandoned now live behind the
// mobile "Controls ▾" toggle, collapsed by default (see the describe block
// below). Existing tests that reach into that group have to open it first —
// this helper is that one step, shared everywhere it's needed.
function openControls() {
  fireEvent.click(screen.getByRole("button", { name: /^controls/i }));
}

describe("<TopBar/>", () => {
  it("the subtitle does NOT contain 'as of last refresh'", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        lastRefreshedAt={new Date(2026, 0, 1, 14, 32)}
      />
    );

    const subtitle = document.querySelector(".topbar__subtitle");
    expect(subtitle).not.toBeNull();
    expect(subtitle!.textContent).not.toMatch(/as of last refresh/i);
  });

  it("formats the subtitle as project name + updated HH:MM when lastRefreshedAt is set", () => {
    render(
      <StatefulTopBar
        {...baseProps()}
        projectName="pip-skills"
        lastRefreshedAt={new Date(2026, 0, 1, 14, 32)}
      />
    );

    expect(screen.getByText("pip-skills · updated 14:32")).toBeInTheDocument();
  });

  it("falls back to just the project name when lastRefreshedAt is null", () => {
    render(<StatefulTopBar {...baseProps()} projectName="pip-skills" lastRefreshedAt={null} />);

    expect(screen.getByText("pip-skills")).toBeInTheDocument();
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

    expect(screen.getByLabelText("Threshold")).toHaveValue(65);
    expect(screen.getByText(/default threshold/i)).toBeInTheDocument();
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

  it("renders a Clear button beside the repo selector when onClear is provided, and clicking it calls onClear", () => {
    const onClear = vi.fn();
    render(<StatefulTopBar {...baseProps()} onClear={onClear} />);

    // WF-085: Clear… lives in the collapsed-by-default Controls group now.
    openControls();
    const button = screen.getByRole("button", { name: /clear/i });
    expect(button).toBeInTheDocument();
    fireEvent.click(button);
    expect(onClear).toHaveBeenCalledTimes(1);
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

// WF-085b: mobile (≤720px) collapses threshold+Set/Clear…/Labels…/Refresh/
// Abandoned behind a single "Controls ▾" toggle. The collapse itself is
// implemented with the native `hidden` attribute (see TopBar.tsx), which
// jsdom's own accessibility-tree logic honours regardless of whether any
// stylesheet is loaded — `getByRole` excludes descendants of a `hidden`
// ancestor by default, and jest-dom's `toBeVisible()` checks
// `hasAttribute('hidden')` directly. That's what lets these tests verify
// real show/hide behaviour without styles.css ever being imported here;
// styles.css itself additionally confines the `[hidden]` override to the
// ≤720px media query so desktop is provably unaffected (see the CSS
// content assertions further down).
describe("<TopBar/> mobile Controls toggle (WF-085)", () => {
  it("collapses the secondary controls by default, hiding them from the accessibility tree", () => {
    render(<StatefulTopBar {...baseProps()} onClear={() => {}} />);

    const toggle = screen.getByRole("button", { name: /^controls/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // WF-085b: the toggle now drives BOTH TopBar's own group AND the
    // separate <FilterBar/> App.tsx renders as a sibling — a
    // space-separated id list in aria-controls is valid WAI-ARIA.
    expect(toggle).toHaveAttribute(
      "aria-controls",
      "topbar-controls-group filter-bar"
    );

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

// WF-085b Build item 1: the repo/branch <select>s truncate a long value
// with an ellipsis instead of wrapping, on every viewport. styles.css is
// never imported by these component tests (only src/main.tsx imports it —
// see the other frontend test files), so there is no computed-style
// signal to assert on from jsdom; instead this reads the real stylesheet
// source and asserts the specific truncation declarations are present on
// the exact selectors TopBar's repo/branch chips render
// (`.topbar__repo-select select` / `.topbar__branch-select select`,
// RepoSelector.tsx / BranchFilter.tsx). This is a regression guard against
// someone dropping the rule later, not a substitute for visual QA.
describe("topbar repo/branch select truncation styling (WF-085b)", () => {
  const css = readFileSync(path.resolve(process.cwd(), "src/styles.css"), "utf-8");

  function ruleBodyFor(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
    expect(match, `expected a CSS rule for ${selector}`).not.toBeNull();
    return match![1];
  }

  it("truncates the repo <select> with an ellipsis instead of wrapping", () => {
    const body = ruleBodyFor(".topbar__repo-select select");
    expect(body).toMatch(/overflow:\s*hidden/);
    expect(body).toMatch(/text-overflow:\s*ellipsis/);
    expect(body).toMatch(/white-space:\s*nowrap/);
    expect(body).toMatch(/min-width:\s*0/);
  });

  it("truncates the branch <select> with an ellipsis instead of wrapping", () => {
    const body = ruleBodyFor(".topbar__branch-select select");
    expect(body).toMatch(/overflow:\s*hidden/);
    expect(body).toMatch(/text-overflow:\s*ellipsis/);
    expect(body).toMatch(/white-space:\s*nowrap/);
    expect(body).toMatch(/min-width:\s*0/);
  });

  it("lets the repo/branch chip wrappers shrink below their content width so the ellipsis can engage", () => {
    expect(ruleBodyFor(".topbar__repo-select")).toMatch(/min-width:\s*0/);
    expect(ruleBodyFor(".topbar__branch-select")).toMatch(/min-width:\s*0/);
  });
});
