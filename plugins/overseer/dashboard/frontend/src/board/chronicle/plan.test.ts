import { describe, expect, it } from "vitest";
import { planLabel, plansPresent } from "./plan";

describe("planLabel", () => {
  it("names the plans we know", () => {
    expect(planLabel("claude_max")).toBe("Max");
    expect(planLabel("claude_enterprise")).toBe("Enterprise");
  });

  it("tidies a plan this build has never heard of rather than dropping it", () => {
    // The set upstream can grow; showing something truthful beats vanishing.
    expect(planLabel("claude_super_duper")).toBe("Super Duper");
  });

  it("renders nothing for an unknown plan — never the word 'unknown'", () => {
    expect(planLabel(null)).toBeNull();
    expect(planLabel(undefined)).toBeNull();
    expect(planLabel("")).toBeNull();
  });
});

describe("plansPresent", () => {
  const s = (plan: string | null) => ({ plan_organization_type: plan });

  it("counts distinct plans, busiest first", () => {
    expect(plansPresent([s("claude_max"), s("claude_enterprise"), s("claude_max")])).toEqual([
      { plan: "claude_max", label: "Max", count: 2 },
      { plan: "claude_enterprise", label: "Enterprise", count: 1 },
    ]);
  });

  it("excludes sessions with no plan — there is no 'unknown' option to pick", () => {
    expect(plansPresent([s(null), s("claude_max"), s(null)])).toEqual([
      { plan: "claude_max", label: "Max", count: 1 },
    ]);
  });

  it("is empty when nothing has a plan, so the filter can hide itself", () => {
    expect(plansPresent([s(null), s(null)])).toEqual([]);
  });
});

describe("plansPresent — a plan that tidies to nothing", () => {
  it("drops it rather than crashing the sort", () => {
    // `planLabel` returns null for a value that tidies away, but the raw
    // value is truthy so it passes the counting guard. Asserted to `string`
    // and handed to `localeCompare`, that null took down the whole page.
    expect(() =>
      plansPresent([{ plan_organization_type: "_" }, { plan_organization_type: "claude_max" }])
    ).not.toThrow();
    expect(plansPresent([
      { plan_organization_type: "_" },
      { plan_organization_type: "-" },
      { plan_organization_type: "claude_" },
      { plan_organization_type: "claude_max" },
    ])).toEqual([{ plan: "claude_max", label: "Max", count: 1 }]);
  });

  it("still keeps an unrecognised plan that DOES tidy to something", () => {
    expect(plansPresent([{ plan_organization_type: "claude_something_new" }]))
      .toEqual([{ plan: "claude_something_new", label: "Something New", count: 1 }]);
  });
});
