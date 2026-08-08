import { describe, expect, it } from "vitest";
import { accentKeyForCard, bannerLabelForCard } from "./cardAccent";
import type { Stage, Status } from "../api/types";

function card(status: Status, stage: Stage | null = null) {
  return { status, stage };
}

describe("accentKeyForCard / bannerLabelForCard", () => {
  it("planned -> backlog", () => {
    expect(accentKeyForCard(card("planned"))).toBe("backlog");
    expect(bannerLabelForCard(card("planned"))).toBe("Backlog");
  });

  it("blocked with no stage -> backlog", () => {
    expect(accentKeyForCard(card("blocked", null))).toBe("backlog");
    expect(bannerLabelForCard(card("blocked", null))).toBe("Backlog");
  });

  const stages: Stage[] = [
    "bootstrap",
    "planning",
    "plan-review",
    "implementation",
    "impl-review",
    "verification",
    "awaiting-merge",
  ];
  const labels: Record<Stage, string> = {
    bootstrap: "Bootstrap",
    planning: "Planning",
    "plan-review": "Plan Review",
    implementation: "Implementation",
    "impl-review": "Impl Review",
    verification: "Verification",
    "awaiting-merge": "Awaiting Merge",
  };

  it.each(stages)("in-flight + stage %s -> that stage's own key/label", (stage) => {
    expect(accentKeyForCard(card("in-flight", stage))).toBe(stage);
    expect(bannerLabelForCard(card("in-flight", stage))).toBe(labels[stage]);
  });

  it.each(stages)("blocked + stage %s -> that stage's own key/label (blocked still counts)", (stage) => {
    expect(accentKeyForCard(card("blocked", stage))).toBe(stage);
    expect(bannerLabelForCard(card("blocked", stage))).toBe(labels[stage]);
  });

  it("parked -> parked", () => {
    expect(accentKeyForCard(card("parked"))).toBe("parked");
    expect(bannerLabelForCard(card("parked"))).toBe("Parked");
  });

  it("done -> done", () => {
    expect(accentKeyForCard(card("done"))).toBe("done");
    expect(bannerLabelForCard(card("done"))).toBe("Done");
  });

  it("abandoned -> accent key 'parked' (taupe reuse) but label 'Archive' (key/label diverge)", () => {
    expect(accentKeyForCard(card("abandoned"))).toBe("parked");
    expect(bannerLabelForCard(card("abandoned"))).toBe("Archive");
  });

  it("defensive fallback: in-flight with no stage (contract violation) -> backlog, mirrors layout.ts", () => {
    expect(accentKeyForCard(card("in-flight", null))).toBe("backlog");
    expect(bannerLabelForCard(card("in-flight", null))).toBe("Backlog");
  });
});
