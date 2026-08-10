import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import LaneIconNav, { type LaneIconNavLane } from "./LaneIconNav";

const lanes: LaneIconNavLane[] = [
  { key: "backlog", label: "Backlog", count: 3, accent: "backlog" },
  {
    key: "stage:implementation",
    label: "Implementation",
    count: 0,
    accent: "implementation",
  },
  { key: "archive", label: "Abandoned", count: 1, accent: "abandoned" },
];

describe("<LaneIconNav/>", () => {
  it("renders one icon + count per lane, aria-labelled with label and count", () => {
    render(<LaneIconNav lanes={lanes} activeKey="backlog" onJump={vi.fn()} />);

    lanes.forEach((lane) => {
      const item = screen.getByLabelText(`${lane.label}, ${lane.count} cards`);
      expect(item).toBeInTheDocument();
      const icon = item.querySelector("img");
      expect(icon).not.toBeNull();
      expect(icon).toHaveAttribute("src", expect.any(String));
      expect(item).toHaveTextContent(String(lane.count));
    });
  });

  it("marks only the lane matching activeKey as active", () => {
    render(<LaneIconNav lanes={lanes} activeKey="archive" onJump={vi.fn()} />);

    expect(
      screen.getByLabelText("Abandoned, 1 cards")
    ).toHaveClass("lane-icon-nav__item--active");
    expect(
      screen.getByLabelText("Backlog, 3 cards")
    ).not.toHaveClass("lane-icon-nav__item--active");
    expect(
      screen.getByLabelText("Implementation, 0 cards")
    ).not.toHaveClass("lane-icon-nav__item--active");
  });

  it("re-renders the active pill when activeKey changes", () => {
    const { rerender } = render(
      <LaneIconNav lanes={lanes} activeKey="backlog" onJump={vi.fn()} />
    );
    expect(screen.getByLabelText("Backlog, 3 cards")).toHaveClass(
      "lane-icon-nav__item--active"
    );

    rerender(
      <LaneIconNav lanes={lanes} activeKey="stage:implementation" onJump={vi.fn()} />
    );
    expect(screen.getByLabelText("Backlog, 3 cards")).not.toHaveClass(
      "lane-icon-nav__item--active"
    );
    expect(
      screen.getByLabelText("Implementation, 0 cards")
    ).toHaveClass("lane-icon-nav__item--active");
  });

  it("calls onJump with the lane's key when clicked", () => {
    const onJump = vi.fn();
    render(<LaneIconNav lanes={lanes} activeKey="backlog" onJump={onJump} />);

    fireEvent.click(screen.getByLabelText("Abandoned, 1 cards"));

    expect(onJump).toHaveBeenCalledTimes(1);
    expect(onJump).toHaveBeenCalledWith("archive");
  });
});
