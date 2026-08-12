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
});
