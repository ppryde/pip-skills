import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import InfoTooltip from "./InfoTooltip";

describe("<InfoTooltip/>", () => {
  it("renders a trigger button found by its aria-label", () => {
    render(<InfoTooltip label="What is Last Orders?">Explanation</InfoTooltip>);
    expect(
      screen.getByRole("button", { name: "What is Last Orders?" })
    ).toBeInTheDocument();
  });

  it("shows no tooltip until the trigger is clicked", () => {
    render(<InfoTooltip label="What is Last Orders?">Explanation</InfoTooltip>);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows the tooltip with its text after a click", () => {
    render(<InfoTooltip label="What is Last Orders?">Explanation text</InfoTooltip>);
    fireEvent.click(screen.getByRole("button", { name: "What is Last Orders?" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Explanation text");
  });

  it("hides the tooltip again on a second click", () => {
    render(<InfoTooltip label="What is Last Orders?">Explanation</InfoTooltip>);
    const trigger = screen.getByRole("button", { name: "What is Last Orders?" });
    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
