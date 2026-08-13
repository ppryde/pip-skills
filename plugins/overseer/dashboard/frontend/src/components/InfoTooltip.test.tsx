import { describe, expect, it, vi } from "vitest";
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

describe("InfoTooltip custom trigger", () => {
  it("renders a custom trigger and toggles the bubble", () => {
    render(<InfoTooltip label="stage" trigger={<span>ICON</span>}>Impl Review</InfoTooltip>);
    fireEvent.click(screen.getByText("ICON"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Impl Review");
  });
  it("stops click propagation to a parent handler", () => {
    const parent = vi.fn();
    render(<div onClick={parent}><InfoTooltip label="s" trigger={<span>ICON</span>}>x</InfoTooltip></div>);
    fireEvent.click(screen.getByText("ICON"));
    expect(parent).not.toHaveBeenCalled();
  });
});
