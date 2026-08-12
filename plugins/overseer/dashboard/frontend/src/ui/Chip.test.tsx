import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Chip from "./Chip";

describe("<Chip/>", () => {
  it("renders a .qb-chip span with its children", () => {
    render(<Chip>7d window</Chip>);
    const chip = screen.getByText("7d window");
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveClass("qb-chip");
  });

  it("composes a caller-supplied className", () => {
    render(<Chip className="topbar__pill">last refreshed 2m ago</Chip>);
    expect(screen.getByText("last refreshed 2m ago")).toHaveClass(
      "qb-chip",
      "topbar__pill"
    );
  });
});
