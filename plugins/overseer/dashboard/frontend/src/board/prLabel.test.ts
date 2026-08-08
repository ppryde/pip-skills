import { describe, expect, it } from "vitest";
import { prLabel } from "./prLabel";

describe("prLabel", () => {
  it("renders number and review_state when both present", () => {
    expect(prLabel({ number: 42, review_state: "approved" })).toBe(
      "PR #42 · approved"
    );
  });

  it("renders just PR when neither number nor review_state is present", () => {
    expect(prLabel({})).toBe("PR");
  });

  it("omits the review_state segment when absent", () => {
    expect(prLabel({ number: 7 })).toBe("PR #7");
  });

  it("omits the number segment when absent", () => {
    expect(prLabel({ review_state: "changes_requested" })).toBe(
      "PR · changes_requested"
    );
  });
});
