import { describe, expect, it } from "vitest";
import { buildParty } from "./party";
import type { BoardCard, SessionSummary } from "../api/types";

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

function session(overrides: Partial<SessionSummary> & { id: string }): SessionSummary {
  return {
    worktree_cwd: "/w",
    updated_at: 100,
    stale: false,
    ...overrides,
  };
}

describe("buildParty", () => {
  it("joins a session to the card it claims", () => {
    const sessions = [session({ id: "sess-1" })];
    const cards = [
      card({ id: "WF-001", title: "Forge the blades", claimed_by: "sess-1" }),
    ];

    const party = buildParty(sessions, cards);

    expect(party).toEqual([
      {
        session: sessions[0],
        questCardId: "WF-001",
        questTitle: "Forge the blades",
      },
    ]);
  });

  it("gives an unclaimed session null quest fields", () => {
    const sessions = [session({ id: "sess-idle" })];
    const cards = [card({ id: "WF-001", claimed_by: null })];

    const party = buildParty(sessions, cards);

    expect(party).toEqual([
      { session: sessions[0], questCardId: null, questTitle: null },
    ]);
  });

  it("gives a session with no matching claimed_by card null quest fields (no cards at all)", () => {
    const sessions = [session({ id: "sess-solo" })];

    const party = buildParty(sessions, []);

    expect(party).toEqual([
      { session: sessions[0], questCardId: null, questTitle: null },
    ]);
  });

  it("still joins a stale session to its claimed card — staleness is a session concern, not a join concern", () => {
    const sessions = [session({ id: "sess-stale", stale: true })];
    const cards = [card({ id: "WF-002", title: "Rest", claimed_by: "sess-stale" })];

    const party = buildParty(sessions, cards);

    expect(party[0].session.stale).toBe(true);
    expect(party[0].questCardId).toBe("WF-002");
  });

  it("produces one PartyMember per session regardless of card count/order", () => {
    const sessions = [
      session({ id: "sess-a" }),
      session({ id: "sess-b" }),
    ];
    const cards = [
      card({ id: "WF-001", claimed_by: "sess-b" }),
      card({ id: "WF-002", claimed_by: null }),
    ];

    const party = buildParty(sessions, cards);

    expect(party).toHaveLength(2);
    expect(party.find((p) => p.session.id === "sess-a")?.questCardId).toBeNull();
    expect(party.find((p) => p.session.id === "sess-b")?.questCardId).toBe(
      "WF-001"
    );
  });

  it("returns an empty array for no sessions", () => {
    expect(buildParty([], [card({ id: "WF-001" })])).toEqual([]);
  });
});
