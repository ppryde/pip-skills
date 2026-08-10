import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type {
  BoardCard,
  BoardResponse,
  Context,
  Limits,
  RateWindow,
  RepoEntry,
} from "../api/types";
import type { PartyMember } from "../board/party";
import TopBar from "./TopBar";

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

describe("<TopBar/>", () => {
  it("the subtitle does NOT contain 'as of last refresh'", () => {
    render(
      <TopBar
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
      <TopBar
        {...baseProps()}
        projectName="pip-skills"
        lastRefreshedAt={new Date(2026, 0, 1, 14, 32)}
      />
    );

    expect(screen.getByText("pip-skills · updated 14:32")).toBeInTheDocument();
  });

  it("falls back to just the project name when lastRefreshedAt is null", () => {
    render(<TopBar {...baseProps()} projectName="pip-skills" lastRefreshedAt={null} />);

    expect(screen.getByText("pip-skills")).toBeInTheDocument();
  });

  it("renders the gold-total pill summed from budget.actual across cards", () => {
    render(
      <TopBar
        {...baseProps()}
        cards={[card({ id: "WF-1", budget: { estimate: null, actual: 500 } }), card({ id: "WF-2", budget: { estimate: null, actual: 250 } })]}
      />
    );

    expect(screen.getByText("750")).toBeInTheDocument();
  });

  it("renders the N / M vanquished pill from done-count over total", () => {
    render(
      <TopBar
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
      <TopBar
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
      <TopBar
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
      <TopBar
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
      <TopBar
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
      <TopBar
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
    render(<TopBar {...baseProps()} context={{ pct: null, threshold: 65 }} />);

    expect(screen.getByLabelText("Threshold")).toHaveValue(65);
    expect(screen.getByText(/default threshold/i)).toBeInTheDocument();
  });

  it("renders no Sessions toggle — the old sessions dropdown retired, the fleet-health pill replaces it", () => {
    render(<TopBar {...baseProps()} />);
    expect(
      screen.queryByRole("button", { name: /^sessions$/i })
    ).not.toBeInTheDocument();
  });

  it("renders no repo selector when no boards are discoverable", () => {
    render(<TopBar {...baseProps()} repos={[]} />);
    expect(screen.queryByLabelText("Repo")).not.toBeInTheDocument();
  });

  it("renders the repo selector with every discovered repo as an option", () => {
    render(
      <TopBar
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
      <TopBar
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
    render(<TopBar {...baseProps()} branches={[]} />);
    expect(screen.queryByLabelText("Branch")).not.toBeInTheDocument();
  });

  it("renders the branch filter with every distinct branch as an option", () => {
    render(
      <TopBar {...baseProps()} branches={["feat/a", "feat/b"]} activeBranch="feat/a" />
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
      <TopBar
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
      <TopBar
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
      <TopBar
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
    render(<TopBar {...baseProps()} limits={{}} />);

    expect(screen.queryByText(/Short Rest/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Long Rest/)).not.toBeInTheDocument();
  });

  // Task 7: Clear-data control — gated entirely on the `onClear` prop so
  // App.tsx can withhold it when no repo is selected (see App.tsx's
  // `selectedRepo ? () => setClearOpen(true) : undefined`).
  it("renders no Clear button when onClear is not provided", () => {
    render(<TopBar {...baseProps()} />);
    expect(
      screen.queryByRole("button", { name: /clear/i })
    ).not.toBeInTheDocument();
  });

  it("renders a Clear button beside the repo selector when onClear is provided, and clicking it calls onClear", () => {
    const onClear = vi.fn();
    render(<TopBar {...baseProps()} onClear={onClear} />);

    const button = screen.getByRole("button", { name: /clear/i });
    expect(button).toBeInTheDocument();
    fireEvent.click(button);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  // Task 10: "＋ New card" — TopBar owns the dialog's open state itself
  // (no App-level prop needed) and hands it TopBar's own `mutate` prop.
  it("renders no New card dialog until the New card button is clicked", () => {
    render(<TopBar {...baseProps()} />);
    expect(screen.getByRole("button", { name: /new card/i })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /new card/i })).not.toBeInTheDocument();
  });

  it("clicking the New card button opens NewCardDialog", () => {
    render(<TopBar {...baseProps()} />);

    fireEvent.click(screen.getByRole("button", { name: /new card/i }));

    expect(screen.getByRole("dialog", { name: /new card/i })).toBeInTheDocument();
  });

  // Task 10 (F10, WF-067): the Labels settings control — TopBar owns the
  // dialog's open state itself, same pattern as "＋ New card" above.
  it("renders no Label colors dialog until the Labels settings button is clicked", () => {
    render(<TopBar {...baseProps()} />);
    expect(screen.getByRole("button", { name: /labels/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: /label colors/i })
    ).not.toBeInTheDocument();
  });

  it("clicking the Labels settings button opens LabelSettingsDialog with the board's distinct labels", () => {
    render(
      <TopBar
        {...baseProps()}
        cards={[
          card({ id: "WF-1", labels: ["policy"] }),
          card({ id: "WF-2", labels: ["architecture"] }),
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /labels/i }));

    expect(
      screen.getByRole("dialog", { name: /label colors/i })
    ).toBeInTheDocument();
    expect(screen.getByText("policy")).toBeInTheDocument();
    expect(screen.getByText("architecture")).toBeInTheDocument();
  });
});
