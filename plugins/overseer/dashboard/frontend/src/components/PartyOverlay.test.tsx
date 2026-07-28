import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PartyOverlay from "./PartyOverlay";
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

describe("<PartyOverlay/>", () => {
  it("renders the title, verbatim helper line, and a hero per party member", () => {
    render(
      <PartyOverlay
        party={[
          member({ session: session({ id: "s1", session_name: "aria" }) }),
          member({ session: session({ id: "s2", session_name: "bram" }) }),
        ]}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("⚔ The Party")).toBeInTheDocument();
    expect(
      screen.getByText("…their mana is the context they have left.")
    ).toBeInTheDocument();
    expect(screen.getByText("aria")).toBeInTheDocument();
    expect(screen.getByText("bram")).toBeInTheDocument();
  });

  it("count badge: N = live sessions, M = total including stale ghosts", () => {
    render(
      <PartyOverlay
        party={[
          member({ session: session({ id: "s1", stale: false }) }),
          member({ session: session({ id: "s2", stale: false }) }),
          member({ session: session({ id: "s3", stale: true }) }),
        ]}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("2 OF 3 HEROES")).toBeInTheDocument();
  });

  it("N equals M when every known session is live", () => {
    render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1" }) })]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText("1 OF 1 HEROES")).toBeInTheDocument();
  });

  it("closes when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<PartyOverlay party={[]} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(<PartyOverlay party={[]} onClose={onClose} />);

    fireEvent.click(screen.getByTestId("party-overlay"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT close when a click inside the sheet bubbles (stopPropagation)", () => {
    const onClose = vi.fn();
    render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", session_name: "aria" }) })]}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<PartyOverlay party={[]} onClose={onClose} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the ON QUEST line for a claimed session", () => {
    render(
      <PartyOverlay
        party={[
          member({
            session: session({ id: "s1" }),
            questCardId: "WF-042",
            questTitle: "Forge the blades",
          }),
        ]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText(/ON QUEST · WF-042/)).toBeInTheDocument();
    expect(screen.getByText("Forge the blades")).toBeInTheDocument();
  });

  it("guards pct === undefined with the neutral unknown treatment, never NaN%", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: undefined }) })]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText("— unknown")).toBeInTheDocument();
    expect(container.querySelector(".hero-card__mana-fill")).toBeNull();
    expect(container.textContent).not.toContain("NaN");
  });

  it("renders the session's branch alongside its class line", () => {
    render(
      <PartyOverlay
        party={[
          member({ session: session({ id: "s1", branch: "feat/night-shift" }) }),
        ]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText("⑃ feat/night-shift")).toBeInTheDocument();
  });

  it("renders no branch line when the session carries no branch", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1" }) })]}
        onClose={vi.fn()}
      />
    );
    expect(container.querySelector(".hero-card__branch")).toBeNull();
  });

  it("spotlights a hero card whose session is on the active branch (WF-031)", () => {
    const { container } = render(
      <PartyOverlay
        party={[
          member({ session: session({ id: "s1", branch: "feat/a" }) }),
          member({ session: session({ id: "s2", branch: "feat/b" }) }),
        ]}
        onClose={vi.fn()}
        activeBranch="feat/a"
      />
    );
    const heroCards = container.querySelectorAll(".hero-card:not(.hero-card--summon)");
    expect(heroCards[0]).toHaveClass("is-spotlight");
    expect(heroCards[1]).not.toHaveClass("is-spotlight");
  });

  it("spotlights nothing when activeBranch is null", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", branch: "feat/a" }) })]}
        onClose={vi.fn()}
        activeBranch={null}
      />
    );
    expect(
      container.querySelector(".hero-card:not(.hero-card--summon).is-spotlight")
    ).toBeNull();
  });

  it("renders the session's explicit ctx% alongside the mana bar (WF-042)", () => {
    render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: 42 }) })]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText("ctx 42%")).toBeInTheDocument();
  });

  it("renders no ctx% line when the session carries no pct", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: undefined }) })]}
        onClose={vi.fn()}
      />
    );
    expect(container.querySelector(".hero-card__ctx")).toBeNull();
  });

  it("renders the session's PR, number and review_state, when present", () => {
    render(
      <PartyOverlay
        party={[
          member({
            session: session({
              id: "s1",
              pr: { number: 42, review_state: "approved" },
            }),
          }),
        ]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText("PR #42 · approved")).toBeInTheDocument();
  });

  it("links the PR when pr.url is present", () => {
    render(
      <PartyOverlay
        party={[
          member({
            session: session({
              id: "s1",
              pr: { number: 42, url: "https://example.com/pr/42" },
            }),
          }),
        ]}
        onClose={vi.fn()}
      />
    );
    const link = screen.getByRole("link", { name: "PR #42" });
    expect(link).toHaveAttribute("href", "https://example.com/pr/42");
  });

  it("renders no PR line when the session carries no pr", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1" }) })]}
        onClose={vi.fn()}
      />
    );
    expect(container.querySelector(".hero-card__pr")).toBeNull();
  });

  it("applies the near-threshold cue when pct >= threshold (WF-042)", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: 90 }) })]}
        onClose={vi.fn()}
        threshold={80}
      />
    );
    const heroCard = container.querySelector(".hero-card:not(.hero-card--summon)");
    expect(heroCard).toHaveClass("is-near-threshold");
  });

  it("does not apply the near-threshold cue when pct is below threshold", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: 50 }) })]}
        onClose={vi.fn()}
        threshold={80}
      />
    );
    const heroCard = container.querySelector(".hero-card:not(.hero-card--summon)");
    expect(heroCard).not.toHaveClass("is-near-threshold");
  });

  it("does not apply the near-threshold cue when threshold is null, regardless of pct", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: 99 }) })]}
        onClose={vi.fn()}
        threshold={null}
      />
    );
    const heroCard = container.querySelector(".hero-card:not(.hero-card--summon)");
    expect(heroCard).not.toHaveClass("is-near-threshold");
  });

  it("does not apply the near-threshold cue when the session has no pct", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1", pct: undefined }) })]}
        onClose={vi.fn()}
        threshold={0}
      />
    );
    const heroCard = container.querySelector(".hero-card:not(.hero-card--summon)");
    expect(heroCard).not.toHaveClass("is-near-threshold");
  });

  it("always renders exactly one static, non-interactive summon slot at the end", () => {
    const { container } = render(
      <PartyOverlay
        party={[member({ session: session({ id: "s1" }) })]}
        onClose={vi.fn()}
      />
    );
    const summonSlots = container.querySelectorAll(".hero-card--summon");
    expect(summonSlots).toHaveLength(1);
    expect(summonSlots[0].tagName).toBe("DIV");
    expect(summonSlots[0].querySelector("button")).toBeNull();
    expect(summonSlots[0]).toHaveTextContent("Summon a hero");
  });
});
