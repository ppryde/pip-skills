import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CostAttributionPanel from "./CostAttributionPanel";

const A = {
  turns: 102414, attributed_turns: 17731,
  cost_usd: 683, unattributed_cost_usd: 14095,
  plugins: [
    { name: "superpowers", turns: 2987, context_tokens: 427_400_000,
      output_tokens: 1_694_000, sessions: 31, cost_usd: 293 },
  ],
  agents: [
    { name: "general-purpose", turns: 10619, context_tokens: 1_032_000_000,
      output_tokens: 847_000, sessions: 60, cost_usd: 390 },
  ],
  skills: [], mcp: [],
};

describe("<CostAttributionPanel/>", () => {
  it("ranks plugins and subagents against each other in one list", () => {
    render(<CostAttributionPanel attribution={A} />);
    // Agents cost more than plugins here; two separate lists would hide it.
    expect(screen.getByText("general-purpose · agent")).toBeInTheDocument();
    expect(screen.getByText("superpowers · plugin")).toBeInTheDocument();
  });

  it("shows the unattributed remainder rather than implying the slice is the bill", () => {
    render(<CostAttributionPanel attribution={A} />);
    expect(screen.getByText("unattributed")).toBeInTheDocument();
    // Total is attributed + unattributed, not the sum of the ranked rows.
    expect(screen.getByText(/\$14\.8k at list prices/)).toBeInTheDocument();
  });

  it("explains an empty panel rather than showing an empty chart", () => {
    render(<CostAttributionPanel />);
    expect(screen.getByText(/chronicle sync --full/)).toBeInTheDocument();
  });
});
