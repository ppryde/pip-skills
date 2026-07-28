import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import PartyColumn from "./PartyColumn";
import type { PartyMember } from "../board/party";
import type { SessionSummary } from "../api/types";

function session(overrides: Partial<SessionSummary> & { id: string }): SessionSummary {
  return {
    worktree_cwd: "/w",
    updated_at: 100,
    stale: false,
    ...overrides,
  };
}

function member(overrides: Partial<PartyMember> & { session: SessionSummary }): PartyMember {
  return {
    questCardId: null,
    questTitle: null,
    ...overrides,
  };
}

describe("<PartyColumn/>", () => {
  it("renders a live session without the stale row class", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1", session_name: "night-shift" }) })]} />
    );
    expect(screen.getByText("night-shift")).toBeInTheDocument();
    const row = container.querySelector(".party-row");
    expect(row).not.toHaveClass("party-row--stale");
  });

  it("renders a stale session as a dimmed ghost row", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1", stale: true }) })]} />
    );
    const row = container.querySelector(".party-row");
    expect(row).toHaveClass("party-row--stale");
    expect(container.querySelector(".party-avatar__dot--stale")).not.toBeNull();
  });

  it("shows the ON QUEST line when the session claims a card", () => {
    render(
      <PartyColumn
        party={[
          member({
            session: session({ id: "s1" }),
            questCardId: "WF-042",
            questTitle: "Forge the blades",
          }),
        ]}
      />
    );
    expect(screen.getByText(/ON QUEST · WF-042 — Forge the blades/)).toBeInTheDocument();
  });

  it("shows no ON QUEST line when the session is unclaimed", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1" }) })]} />
    );
    expect(container.querySelector(".party-row__quest")).toBeNull();
  });

  it("guards pct === undefined with the neutral unknown treatment, never NaN%", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1", pct: undefined }) })]} />
    );
    expect(screen.getByText("— unknown")).toBeInTheDocument();
    expect(container.querySelector(".party-row__mana-fill")).toBeNull();
    expect(container.textContent).not.toContain("NaN");
  });

  it("renders the mana fill at 100 - pct width when pct is defined", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1", pct: 30 }) })]} />
    );
    const fill = container.querySelector<HTMLElement>(".party-row__mana-fill");
    expect(fill).not.toBeNull();
    expect(fill!.style.width).toBe("70%");
    expect(fill).toHaveClass("party-row__mana-fill--high");
  });

  it("uses the low-mana gradient when remaining mana is under 50%", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1", pct: 80 }) })]} />
    );
    const fill = container.querySelector<HTMLElement>(".party-row__mana-fill");
    expect(fill!.style.width).toBe("20%");
    expect(fill).toHaveClass("party-row__mana-fill--low");
  });

  it("renders a model as the hero's class line when present", () => {
    render(
      <PartyColumn party={[member({ session: session({ id: "s1", model: "Opus" }) })]} />
    );
    expect(screen.getByText("Opus")).toBeInTheDocument();
  });

  it("renders nothing (no rows) for an empty party", () => {
    const { container } = render(<PartyColumn party={[]} activeBranch={null} />);
    expect(container.querySelectorAll(".party-row")).toHaveLength(0);
  });

  it("renders the session's branch alongside its class line", () => {
    render(
      <PartyColumn
        party={[
          member({ session: session({ id: "s1", branch: "feat/night-shift" }) }),
        ]}
        activeBranch={null}
      />
    );
    expect(screen.getByText("⑃ feat/night-shift")).toBeInTheDocument();
  });

  it("renders no branch line when the session carries no branch", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1" }) })]} activeBranch={null} />
    );
    expect(container.querySelector(".party-row__branch")).toBeNull();
  });

  it("spotlights a row whose session is on the active branch (WF-031)", () => {
    const { container } = render(
      <PartyColumn
        party={[
          member({ session: session({ id: "s1", branch: "feat/a" }) }),
          member({ session: session({ id: "s2", branch: "feat/b" }) }),
        ]}
        activeBranch="feat/a"
      />
    );
    const rows = container.querySelectorAll(".party-row");
    expect(rows[0]).toHaveClass("is-spotlight");
    expect(rows[1]).not.toHaveClass("is-spotlight");
  });

  it("spotlights nothing when activeBranch is null", () => {
    const { container } = render(
      <PartyColumn
        party={[member({ session: session({ id: "s1", branch: "feat/a" }) })]}
        activeBranch={null}
      />
    );
    expect(container.querySelector(".is-spotlight")).toBeNull();
  });

  it("renders the session's explicit ctx% alongside the mana bar (WF-042)", () => {
    render(
      <PartyColumn party={[member({ session: session({ id: "s1", pct: 42 }) })]} />
    );
    expect(screen.getByText("ctx 42%")).toBeInTheDocument();
  });

  it("renders no ctx% line when the session carries no pct", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1", pct: undefined }) })]} />
    );
    expect(container.querySelector(".party-row__ctx")).toBeNull();
  });

  it("renders the session's PR, linked when pr.url is present", () => {
    render(
      <PartyColumn
        party={[
          member({
            session: session({
              id: "s1",
              pr: { number: 9, review_state: "pending", url: "https://example.com/pr/9" },
            }),
          }),
        ]}
      />
    );
    const link = screen.getByRole("link", { name: "PR #9 · pending" });
    expect(link).toHaveAttribute("href", "https://example.com/pr/9");
  });

  it("renders no PR line when the session carries no pr", () => {
    const { container } = render(
      <PartyColumn party={[member({ session: session({ id: "s1" }) })]} />
    );
    expect(container.querySelector(".party-row__pr")).toBeNull();
  });

  it("applies the near-threshold cue when pct >= threshold (WF-042)", () => {
    const { container } = render(
      <PartyColumn
        party={[member({ session: session({ id: "s1", pct: 90 }) })]}
        threshold={80}
      />
    );
    expect(container.querySelector(".party-row")).toHaveClass("is-near-threshold");
  });

  it("does not apply the near-threshold cue when pct is below threshold or threshold is null", () => {
    const { container: below } = render(
      <PartyColumn
        party={[member({ session: session({ id: "s1", pct: 50 }) })]}
        threshold={80}
      />
    );
    expect(below.querySelector(".party-row")).not.toHaveClass("is-near-threshold");

    const { container: noThreshold } = render(
      <PartyColumn
        party={[member({ session: session({ id: "s1", pct: 99 }) })]}
        threshold={null}
      />
    );
    expect(noThreshold.querySelector(".party-row")).not.toHaveClass(
      "is-near-threshold"
    );
  });
});
