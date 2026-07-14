import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { BoardCard, BoardResponse, Context, Limits } from "../api/types";
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

  it("renders no Sessions toggle — SessionsPanel retired, the questing pill replaces it", () => {
    render(<TopBar {...baseProps()} />);
    expect(
      screen.queryByRole("button", { name: /^sessions$/i })
    ).not.toBeInTheDocument();
  });
});
