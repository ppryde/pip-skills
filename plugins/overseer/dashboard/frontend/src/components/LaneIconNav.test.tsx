import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import LaneIconNav, { type LaneIconNavLane } from "./LaneIconNav";

// Every lane here is non-empty (count > 0) — the generic aria-label
// template (`${label}, ${count} cards`) only holds for non-empty lanes;
// an empty (count === 0) lane gets its own ", empty" suffix + disabled
// treatment, covered separately below.
const lanes: LaneIconNavLane[] = [
  { key: "backlog", label: "Backlog", count: 3, accent: "backlog" },
  {
    key: "stage:implementation",
    label: "Implementation",
    count: 2,
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
      screen.getByLabelText("Implementation, 2 cards")
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
      screen.getByLabelText("Implementation, 2 cards")
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

// mobile-v2 refinement: an empty lane (count === 0) still gets a box in the
// strip (completeness/even spacing), but there's no swipe pane behind it to
// jump to (`.lane--empty` is a non-snapping sliver in styles.css) — so its
// box is faded, disabled, and never wired to `onJump`.
describe("<LaneIconNav/> empty-lane treatment (mobile-v2)", () => {
  const withEmpty: LaneIconNavLane[] = [
    { key: "backlog", label: "Backlog", count: 3, accent: "backlog" },
    { key: "stage:bootstrap", label: "Bootstrap", count: 0, accent: "bootstrap" },
  ];

  it("renders an empty lane's icon with an ', empty' aria-label and a literal 0 count", () => {
    render(<LaneIconNav lanes={withEmpty} activeKey="backlog" onJump={vi.fn()} />);

    const item = screen.getByLabelText("Bootstrap, 0 cards, empty");
    expect(item).toBeInTheDocument();
    expect(item).toHaveTextContent("0");
  });

  it("disables the empty lane's box and fades it via the --empty modifier class", () => {
    render(<LaneIconNav lanes={withEmpty} activeKey="backlog" onJump={vi.fn()} />);

    const item = screen.getByLabelText("Bootstrap, 0 cards, empty");
    expect(item).toBeDisabled();
    expect(item).toHaveClass("lane-icon-nav__item--empty");
  });

  it("never calls onJump for an empty lane's box, even when clicked", () => {
    const onJump = vi.fn();
    render(<LaneIconNav lanes={withEmpty} activeKey="backlog" onJump={onJump} />);

    fireEvent.click(screen.getByLabelText("Bootstrap, 0 cards, empty"));

    expect(onJump).not.toHaveBeenCalled();
  });

  it("a non-empty lane alongside it stays a normal, enabled tap target", () => {
    render(<LaneIconNav lanes={withEmpty} activeKey="backlog" onJump={vi.fn()} />);

    const backlog = screen.getByLabelText("Backlog, 3 cards");
    expect(backlog).not.toBeDisabled();
    expect(backlog).not.toHaveClass("lane-icon-nav__item--empty");
  });
});
