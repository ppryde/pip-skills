import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type {
  BoardCard,
  BoardResponse,
  Context,
  Limits,
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
    checklist: [],
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
  it("renders 'as of last refresh' as visible text, scoped to the ctx-note span (belt-and-braces vs. the new subtitle's own timestamp copy)", () => {
    render(<TopBar {...baseProps()} context={{ pct: 42, threshold: 80 }} />);

    const note = document.querySelector(".topbar__ctx-note");
    expect(note).not.toBeNull();
    expect(note).toHaveTextContent(/as of last refresh/i);
  });

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

  it("the questing pill counts only live (non-stale) party members", () => {
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

    expect(screen.getByText("2 questing")).toBeInTheDocument();
  });

  it("clicking the questing pill calls onOpenParty", () => {
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

  it("renders no Sessions toggle — the old sessions dropdown retired, the questing pill replaces it", () => {
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
          { label: "repo-a", root: "/a", current: true },
          { label: "repo-b", root: "/b", current: false },
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
          { label: "repo-a", root: "/a", current: true },
          { label: "repo-b", root: "/b", current: false },
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
});
