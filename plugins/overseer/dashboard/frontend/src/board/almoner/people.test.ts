import { describe, expect, it } from "vitest";
import type { AlmonerItem } from "../../api/types";
import { formatWait, whosWaiting } from "./people";

const NOW = Date.parse("2026-09-13T12:00:00Z");

function item(over: Partial<AlmonerItem> = {}): AlmonerItem {
  return { id: "i1", source: "slack", context: "work", title: "DM", ...over };
}

describe("whosWaiting", () => {
  it("lists a person who is still awaiting a reply as owed", () => {
    const [person] = whosWaiting(
      [item({ who: "Rhona", awaiting: true, arrived: "2026-09-13T10:00:00Z" })],
      NOW
    );
    expect(person).toMatchObject({ name: "Rhona", owed: true, waitedMs: 2 * 3600_000 });
  });

  it("marks someone you answered last as clear, not owed", () => {
    // The last-speaker rule, surfaced as a person-level state: "clear" is
    // earned, not merely "nothing arrived".
    const [person] = whosWaiting([item({ who: "Tomas", awaiting: false })], NOW);
    expect(person).toMatchObject({ name: "Tomas", owed: false });
  });

  it("collapses several asks from one person into one entry", () => {
    const people = whosWaiting(
      [
        item({ id: "a", who: "Rhona", awaiting: true, arrived: "2026-09-13T11:00:00Z" }),
        item({ id: "b", who: "Rhona", awaiting: true, arrived: "2026-09-13T09:00:00Z" }),
      ],
      NOW
    );
    expect(people).toHaveLength(1);
    expect(people[0].count).toBe(2);
  });

  it("takes the LONGEST wait, not the most recent message", () => {
    // How long someone has been waiting is when they first asked, not when
    // they last nudged.
    const [person] = whosWaiting(
      [
        item({ id: "a", who: "Rhona", awaiting: true, arrived: "2026-09-13T11:00:00Z" }),
        item({ id: "b", who: "Rhona", awaiting: true, arrived: "2026-09-13T09:00:00Z" }),
      ],
      NOW
    );
    expect(person.waitedMs).toBe(3 * 3600_000);
  });

  it("orders the owed by longest wait, ahead of everyone clear", () => {
    const people = whosWaiting(
      [
        item({ id: "a", who: "Short", awaiting: true, arrived: "2026-09-13T11:00:00Z" }),
        item({ id: "b", who: "Clear", awaiting: false }),
        item({ id: "c", who: "Long", awaiting: true, arrived: "2026-09-13T08:00:00Z" }),
      ],
      NOW
    );
    expect(people.map((p) => p.name)).toEqual(["Long", "Short", "Clear"]);
  });

  it("treats a person with any open ask as owed, even with settled ones too", () => {
    const [person] = whosWaiting(
      [
        item({ id: "a", who: "Rhona", awaiting: false }),
        item({ id: "b", who: "Rhona", awaiting: true, arrived: "2026-09-13T11:00:00Z" }),
      ],
      NOW
    );
    expect(person.owed).toBe(true);
    // Only the open asks count towards the wait — a settled thread is not a debt.
    expect(person.waitedMs).toBe(3600_000);
  });

  it("ignores items nobody sent", () => {
    // Derived reconcile checks have no person to owe.
    expect(whosWaiting([item({ asks: "reconcile", awaiting: true })], NOW)).toEqual([]);
  });

  it("caps the strip so it never becomes a directory of ghosts", () => {
    const many = Array.from({ length: 12 }, (_, index) =>
      item({ id: `i${index}`, who: `P${index}`, awaiting: false })
    );
    expect(whosWaiting(many, NOW, 6)).toHaveLength(6);
  });

  it("never drops someone who is owed in order to show someone who is clear", () => {
    // The cap must bite on the cleared first — the strip is "who I am holding
    // up", and an owed person falling off it is the one unacceptable outcome.
    const items = [
      ...Array.from({ length: 5 }, (_, i) => item({ id: `c${i}`, who: `Clear${i}`, awaiting: false })),
      item({ id: "o1", who: "Owed", awaiting: true, arrived: "2026-09-13T08:00:00Z" }),
    ];
    const names = whosWaiting(items, NOW, 3).map((p) => p.name);
    expect(names[0]).toBe("Owed");
    expect(names).toHaveLength(3);
  });

  it("never drops an owed person even when owed people alone outnumber the cap", () => {
    // Sorting owed-first before slicing was not enough on its own: when
    // there are MORE owed people than `cap`, a plain `slice(0, cap)` still
    // cuts into the owed end, silently vanishing whichever owed people
    // sorted past the cut — exactly what the doc comment forbids.
    const items = Array.from({ length: 10 }, (_, i) =>
      item({ id: `o${i}`, who: `Owed${i}`, awaiting: true, arrived: "2026-09-13T08:00:00Z" })
    );
    const people = whosWaiting(items, NOW, 8);
    expect(people).toHaveLength(10);
    expect(people.every((p) => p.owed)).toBe(true);
  });

  it("still caps the cleared tail when owed people alone already fill the cap", () => {
    const items = [
      ...Array.from({ length: 8 }, (_, i) =>
        item({ id: `o${i}`, who: `Owed${i}`, awaiting: true, arrived: "2026-09-13T08:00:00Z" })
      ),
      ...Array.from({ length: 5 }, (_, i) => item({ id: `c${i}`, who: `Clear${i}`, awaiting: false })),
    ];
    const people = whosWaiting(items, NOW, 8);
    expect(people).toHaveLength(8);
    expect(people.every((p) => p.owed)).toBe(true);
  });

  it("gives an initial for the disc", () => {
    expect(whosWaiting([item({ who: "rhona baird", awaiting: true })], NOW)[0].initial).toBe("R");
  });

  it("survives an item with an arrival time it cannot parse", () => {
    const [person] = whosWaiting([item({ who: "Rhona", awaiting: true, arrived: "nope" })], NOW);
    expect(person.waitedMs).toBeNull();
  });
});

describe("formatWait", () => {
  it("renders minutes, hours and days", () => {
    expect(formatWait(30 * 60_000)).toBe("30m");
    expect(formatWait(3 * 3600_000)).toBe("3h");
    expect(formatWait(2 * 86_400_000)).toBe("2d");
  });

  it("renders nothing when there is nothing to time", () => {
    expect(formatWait(null)).toBe("");
  });

  it("clamps a negative wait rather than rendering a negative age", () => {
    // Clock skew between providers is real and allowed for elsewhere.
    expect(formatWait(-5000)).toBe("just now");
  });
});
