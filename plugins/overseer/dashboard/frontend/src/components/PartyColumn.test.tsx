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
    const { container } = render(<PartyColumn party={[]} />);
    expect(container.querySelectorAll(".party-row")).toHaveLength(0);
  });
});
