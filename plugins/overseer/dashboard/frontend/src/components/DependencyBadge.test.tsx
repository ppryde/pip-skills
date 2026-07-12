import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DependencyBadge from "./DependencyBadge";

describe("<DependencyBadge/>", () => {
  it("renders a green 'ready' badge when ready AND deps are present", () => {
    render(<DependencyBadge card={{ ready: true, depends_on: ["WF-1"] }} />);
    const badge = screen.getByText("ready");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("dep-badge--ready");
  });

  it("renders an amber 'waiting on' badge when not ready with deps", () => {
    render(
      <DependencyBadge card={{ ready: false, depends_on: ["WF-1", "WF-2"] }} />
    );
    const badge = screen.getByText(/waiting on WF-1, WF-2/);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("dep-badge--waiting");
  });

  it("renders nothing when there are no deps", () => {
    const { container } = render(
      <DependencyBadge card={{ ready: true, depends_on: [] }} />
    );
    expect(container.firstChild).toBeNull();
  });
});
