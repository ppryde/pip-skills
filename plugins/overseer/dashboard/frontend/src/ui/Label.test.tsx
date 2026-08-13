import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Label from "./Label";

describe("<Label/>", () => {
  it("renders a .qb-label span with its children", () => {
    render(<Label>repo</Label>);
    const label = screen.getByText("repo");
    expect(label.tagName).toBe("SPAN");
    expect(label).toHaveClass("qb-label");
  });

  it("renders as an <h3> with the same .qb-label class when as=\"h3\" (card-drawer section headings)", () => {
    render(<Label as="h3">Sub-quests</Label>);
    const heading = screen.getByRole("heading", { level: 3, name: "Sub-quests" });
    expect(heading.tagName).toBe("H3");
    expect(heading).toHaveClass("qb-label");
  });
});
