import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { RepoEntry } from "../api/types";
import UnbegunHolding from "./UnbegunHolding";

function repo(overrides: Partial<RepoEntry> & { label: string; root: string }): RepoEntry {
  return { current: false, has_board: false, live_sessions: 0, ...overrides };
}

describe("<UnbegunHolding/>", () => {
  it("shows the repo's label in the quest copy", () => {
    render(
      <UnbegunHolding
        repo={repo({ label: "sandbox", root: "/repos/sandbox" })}
        liveSessions={3}
      />
    );

    expect(screen.getByText(/quest has not yet begun/i)).toBeInTheDocument();
    expect(screen.getByText("sandbox")).toBeInTheDocument();
  });

  it("names the repo root in the overseer init command", () => {
    render(
      <UnbegunHolding
        repo={repo({ label: "sandbox", root: "/repos/sandbox" })}
        liveSessions={3}
      />
    );

    expect(screen.getByText("overseer init")).toBeInTheDocument();
    expect(screen.getByText("/repos/sandbox")).toBeInTheDocument();
  });

  it("pluralises 'adventurer' for exactly 1 live session", () => {
    render(
      <UnbegunHolding
        repo={repo({ label: "sandbox", root: "/repos/sandbox" })}
        liveSessions={1}
      />
    );

    expect(screen.getByText(/1 adventurer already roam/i)).toBeInTheDocument();
  });

  it("pluralises 'adventurers' for 0 or more than 1 live sessions", () => {
    const { rerender } = render(
      <UnbegunHolding
        repo={repo({ label: "sandbox", root: "/repos/sandbox" })}
        liveSessions={6}
      />
    );
    expect(screen.getByText(/6 adventurers already roam/i)).toBeInTheDocument();

    rerender(
      <UnbegunHolding
        repo={repo({ label: "sandbox", root: "/repos/sandbox" })}
        liveSessions={0}
      />
    );
    expect(screen.getByText(/0 adventurers already roam/i)).toBeInTheDocument();
  });
});
