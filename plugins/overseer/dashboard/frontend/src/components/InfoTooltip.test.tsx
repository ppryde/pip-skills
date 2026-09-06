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

describe("InfoTooltip stays on screen", () => {
  function rect(r: Partial<DOMRect>): DOMRect {
    return { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON: () => ({}), ...r } as DOMRect;
  }

  it("hangs from the trigger's right edge and sits above when the default place overflows", () => {
    // jsdom lays nothing out, so stand in for the measurement: a 240×80
    // bubble whose default (below, left-flush) box runs off both the right
    // and the bottom of a 320×400 viewport.
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(320);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(400);
    const spy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue(rect({ left: 260, right: 500, top: 380, bottom: 460, width: 240, height: 80 }));
    try {
      render(<InfoTooltip label="About API costs">A yardstick, not a bill.</InfoTooltip>);
      fireEvent.click(screen.getByRole("button", { name: "About API costs" }));
      const bubble = screen.getByRole("tooltip");
      expect(bubble).toHaveAttribute("data-align", "end");
      expect(bubble).toHaveAttribute("data-side", "top");
    } finally {
      spy.mockRestore();
      vi.restoreAllMocks();
    }
  });

  it("keeps the default place when the bubble fits", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1200);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
    const spy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue(rect({ left: 20, right: 260, top: 40, bottom: 120, width: 240, height: 80 }));
    try {
      render(<InfoTooltip label="About API costs">A yardstick, not a bill.</InfoTooltip>);
      fireEvent.click(screen.getByRole("button", { name: "About API costs" }));
      const bubble = screen.getByRole("tooltip");
      expect(bubble).toHaveAttribute("data-align", "start");
      expect(bubble).toHaveAttribute("data-side", "bottom");
    } finally {
      spy.mockRestore();
      vi.restoreAllMocks();
    }
  });
});
