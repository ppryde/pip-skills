import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsagePanel from "./UsagePanel";

describe("UsagePanel", () => {
  it("renders a heading, subtitle and one row per entry", () => {
    render(
      <UsagePanel
        title="MCP"
        subtitle="2,488 calls across 51 sessions"
        rows={[
          { label: "playwright", value: 1621, detail: "17 tools" },
          { label: "claude-in-chrome", value: 303 },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "MCP" })).toBeInTheDocument();
    expect(screen.getByText("2,488 calls across 51 sessions")).toBeInTheDocument();
    expect(screen.getByText("playwright")).toBeInTheDocument();
    expect(screen.getByText("claude-in-chrome")).toBeInTheDocument();
  });

  it("shows the empty hint rather than a bare zero when there is nothing", () => {
    render(
      <UsagePanel
        title="Plugins"
        subtitle="none recorded"
        rows={[]}
        emptyHint="Run `chronicle sync --full` to backfill plugin usage."
      />,
    );
    expect(screen.getByText(/chronicle sync --full/)).toBeInTheDocument();
  });
});
