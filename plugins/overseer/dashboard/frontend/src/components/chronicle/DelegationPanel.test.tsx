import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DelegationPanel from "./DelegationPanel";

const D = {
  turns: 102414, subagent_turns: 61102,
  output_tokens: 42_600_000, subagent_output_tokens: 5_600_000,
  tool_calls: 108555, subagent_tool_calls: 68346,
};

describe("<DelegationPanel/>", () => {
  it("shows the gap between what subagents do and what they produce", () => {
    render(<DelegationPanel delegation={D} />);
    // The finding: most of the turns and tool calls, little of the prose.
    expect(screen.getByText("60%")).toBeInTheDocument();   // turns
    expect(screen.getByText("63%")).toBeInTheDocument();   // tool calls
    expect(screen.getByText("13%")).toBeInTheDocument();   // output tokens
  });

  it("puts the raw counts behind each row rather than only a percentage", () => {
    const { container } = render(<DelegationPanel delegation={D} />);
    const row = container.querySelector(".chr-shares__row") as HTMLElement;
    expect(row.title).toContain("of");
  });

  it("says so plainly when there is nothing to divide", () => {
    render(<DelegationPanel delegation={{ ...D, turns: 0, subagent_turns: 0 }} />);
    expect(screen.getByText("No turns in this window.")).toBeInTheDocument();
  });

  it("renders without a delegation block at all", () => {
    render(<DelegationPanel />);
    expect(screen.getByRole("heading", { name: "Delegation" })).toBeInTheDocument();
  });
});
