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
