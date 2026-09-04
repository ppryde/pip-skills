import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import PartyAvatar from "./PartyAvatar";
import type { SessionSummary } from "../api/types";

function session(overrides: Partial<SessionSummary> & { id: string }): SessionSummary {
  return {
    worktree_cwd: "/w",
    updated_at: 100,
    stale: false,
    ...overrides,
  };
}

describe("<PartyAvatar/> branch (WF-031)", () => {
  it("carries a title tooltip naming the branch when the session has one", () => {
    const { container } = render(
      <PartyAvatar session={session({ id: "s1", branch: "feat/night-shift" })} />
    );
    expect(container.querySelector(".party-avatar")).toHaveAttribute(
      "title",
      "on feat/night-shift"
    );
  });

  it("carries no title tooltip when the session has no branch", () => {
    const { container } = render(<PartyAvatar session={session({ id: "s1" })} />);
    expect(container.querySelector(".party-avatar")).not.toHaveAttribute("title");
  });
});

describe("<PartyAvatar/> dot states", () => {
  function dot(s: SessionSummary) {
    const { container } = render(<PartyAvatar session={s} />);
    return container.querySelector(".party-avatar__dot")!;
  }

  it("a working session's dot is plain — it keeps the pulse", () => {
    const el = dot(session({ id: "s1" }));
    expect(el).not.toHaveClass("party-avatar__dot--stale");
    expect(el).not.toHaveClass("party-avatar__dot--idle");
  });

  it("an idle session's dot is marked idle, not stale", () => {
    const el = dot(session({ id: "s1", idle: true }));
    expect(el).toHaveClass("party-avatar__dot--idle");
    expect(el).not.toHaveClass("party-avatar__dot--stale");
  });

  it("stale wins over idle — a dead session is a ghost, not a dozer", () => {
    const el = dot(session({ id: "s1", stale: true, idle: true }));
    expect(el).toHaveClass("party-avatar__dot--stale");
    expect(el).not.toHaveClass("party-avatar__dot--idle");
  });
});
