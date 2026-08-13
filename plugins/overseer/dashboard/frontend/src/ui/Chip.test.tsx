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

  it("adds the matching label-chip--<tone> colour class when tone is given", () => {
    render(<Chip tone="sky">ui</Chip>);
    expect(screen.getByText("ui")).toHaveClass("qb-chip", "label-chip--sky");
  });

  it("composes tone with a caller-supplied className (the wobble shape)", () => {
    render(
      <Chip tone="terracotta" className="label-chip">
        architecture
      </Chip>
    );
    expect(screen.getByText("architecture")).toHaveClass(
      "qb-chip",
      "label-chip--terracotta",
      "label-chip"
    );
  });

  it("omits the tone class entirely when tone is not given", () => {
    render(<Chip>7d window</Chip>);
    const chip = screen.getByText("7d window");
    expect(chip.className).toBe("qb-chip");
  });
});
