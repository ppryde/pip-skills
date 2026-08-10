import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import LabelFilterPopover from "./LabelFilterPopover";
import { labelColor } from "../board/labelColor";

describe("<LabelFilterPopover/>", () => {
  it("renders a chip per label and cycles on click", () => {
    const onCycle = vi.fn();
    render(
      <LabelFilterPopover
        labels={["ui", "api"]}
        includeLabels={[]}
        excludeLabels={["future"]}
        onCycle={onCycle}
        onClose={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /^ui/i }));
    expect(onCycle).toHaveBeenCalledWith("ui");
  });

  it("reflects include/exclude state on the chip", () => {
    render(
      <LabelFilterPopover
        labels={["ui", "future"]}
        includeLabels={["ui"]}
        excludeLabels={["future"]}
        onCycle={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(
      screen.getByRole("button", { name: /ui.*includ/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /future.*exclud/i })
    ).toBeInTheDocument();
  });

  it("gives a neutral label a neutral aria-label", () => {
    render(
      <LabelFilterPopover
        labels={["ui"]}
        includeLabels={[]}
        excludeLabels={[]}
        onCycle={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(
      screen.getByRole("button", { name: "ui: neutral" })
    ).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <LabelFilterPopover
        labels={["ui"]}
        includeLabels={[]}
        excludeLabels={[]}
        onCycle={vi.fn()}
        onClose={onClose}
      />
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when the backdrop (outside the chip sheet) is clicked", () => {
    const onClose = vi.fn();
    render(
      <LabelFilterPopover
        labels={["ui"]}
        includeLabels={[]}
        excludeLabels={[]}
        onCycle={vi.fn()}
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByTestId("label-filter-popover-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT close when a click inside the popover sheet bubbles (stopPropagation)", () => {
    const onClose = vi.fn();
    render(
      <LabelFilterPopover
        labels={["ui"]}
        includeLabels={[]}
        excludeLabels={[]}
        onCycle={vi.fn()}
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("colours a chip from the F10 registry when the label has an entry (WF-067)", () => {
    const hashKey = labelColor("ui");
    const overrideKey = (
      ["slate", "sage", "plum", "clay", "sky", "violet", "olive", "terracotta", "teal"] as const
    ).find((k) => k !== hashKey)!;
    render(
      <LabelFilterPopover
        labels={["ui"]}
        includeLabels={[]}
        excludeLabels={[]}
        onCycle={vi.fn()}
        onClose={vi.fn()}
        colorRegistry={{ ui: overrideKey }}
      />
    );
    const chip = screen.getByRole("button", { name: "ui: neutral" });
    expect(chip.className).toContain(`label-chip--${overrideKey}`);
  });
});
