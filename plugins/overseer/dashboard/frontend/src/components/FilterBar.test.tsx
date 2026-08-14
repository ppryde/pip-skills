import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import FilterBar from "./FilterBar";
import { DEFAULT_FILTER } from "../board/cardFilter";

const base = {
  filter: DEFAULT_FILTER,
  labels: [] as string[],
  visibleCount: 0,
  totalCount: 0,
  isDefault: true,
  onQuery: () => {},
  onCycleLabel: () => {},
  onPriority: () => {},
  onComplexity: () => {},
  onEpicsOnly: () => {},
  onClear: () => {},
  // Expanded by default here so every other test in this file (all
  // exercising the bar's own controls, not the collapse behaviour) keeps
  // finding a reachable/visible bar without opting in per-test — the
  // collapse itself is covered by the dedicated describe block below.
  filtersOpen: true,
};

describe("<FilterBar/>", () => {
  it("typing in search calls onQuery", () => {
    const onQuery = vi.fn();
    render(<FilterBar {...base} onQuery={onQuery} />);
    fireEvent.change(screen.getByLabelText(/search/i), {
      target: { value: "frob" },
    });
    expect(onQuery).toHaveBeenCalledWith("frob");
  });

  it("choosing a priority calls onPriority with the value (null for the placeholder)", () => {
    const onPriority = vi.fn();
    render(<FilterBar {...base} onPriority={onPriority} />);
    fireEvent.change(screen.getByLabelText(/priority/i), {
      target: { value: "P0" },
    });
    expect(onPriority).toHaveBeenCalledWith("P0");
    fireEvent.change(screen.getByLabelText(/priority/i), {
      target: { value: "" },
    });
    expect(onPriority).toHaveBeenCalledWith(null);
  });

  it("toggling Epics only calls onEpicsOnly with the flipped value and reflects aria-pressed", () => {
    const onEpicsOnly = vi.fn();
    const { rerender } = render(<FilterBar {...base} onEpicsOnly={onEpicsOnly} />);
    const btn = screen.getByRole("button", { name: /epics only/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    expect(onEpicsOnly).toHaveBeenCalledWith(true);
    rerender(
      <FilterBar {...base} filter={{ ...DEFAULT_FILTER, epicsOnly: true }} onEpicsOnly={onEpicsOnly} />
    );
    expect(screen.getByRole("button", { name: /epics only/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("choosing a complexity calls onComplexity with the value (null for the placeholder)", () => {
    const onComplexity = vi.fn();
    render(<FilterBar {...base} onComplexity={onComplexity} />);
    fireEvent.change(screen.getByLabelText(/complexity/i), {
      target: { value: "L" },
    });
    expect(onComplexity).toHaveBeenCalledWith("L");
    fireEvent.change(screen.getByLabelText(/complexity/i), {
      target: { value: "" },
    });
    expect(onComplexity).toHaveBeenCalledWith(null);
  });

  it("shows visible/total and disables Clear when default", () => {
    render(<FilterBar {...base} visibleCount={5} totalCount={20} isDefault={true} />);
    expect(screen.getByText(/5 of 20/)).toBeInTheDocument();
    // Exact "Clear" (no ellipsis) — distinguishes this from the topbar's
    // own "Clear…"/ClearDialog button (see App.test.tsx).
    expect(screen.getByRole("button", { name: "Clear" })).toBeDisabled();
  });

  it("enables Clear and calls onClear when not default", () => {
    const onClear = vi.fn();
    render(<FilterBar {...base} isDefault={false} onClear={onClear} />);
    const clearBtn = screen.getByRole("button", { name: "Clear" });
    expect(clearBtn).not.toBeDisabled();
    fireEvent.click(clearBtn);
    expect(onClear).toHaveBeenCalled();
  });

  it("Labels button toggles the popover", () => {
    render(<FilterBar {...base} labels={["ui"]} />);
    fireEvent.click(screen.getByRole("button", { name: /labels/i }));
    expect(screen.getByRole("button", { name: /^ui/i })).toBeInTheDocument();
  });

  it("shows a badge on the Labels button reflecting include+exclude counts", () => {
    render(
      <FilterBar
        {...base}
        filter={{ ...DEFAULT_FILTER, includeLabels: ["a"], excludeLabels: ["b", "c"] }}
      />
    );
    expect(screen.getByRole("button", { name: /labels/i })).toHaveTextContent("3");
  });

  it("closes the popover when it fires onClose", () => {
    render(<FilterBar {...base} labels={["ui"]} />);
    fireEvent.click(screen.getByRole("button", { name: /labels/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  // WF-092: priority/complexity dropped their standalone visible label in
  // favour of the field name as the select's own default-option
  // placeholder — accessibility now rides solely on each select's
  // `aria-label` ("priority"/"complexity"), not adjacent text.
  it("shows the field name as the unset placeholder option, not a standalone label", () => {
    render(<FilterBar {...base} />);
    const prioritySelect = screen.getByLabelText(/priority/i) as HTMLSelectElement;
    const complexitySelect = screen.getByLabelText(/complexity/i) as HTMLSelectElement;
    expect(prioritySelect.options[0]).toHaveTextContent("Priority");
    expect(complexitySelect.options[0]).toHaveTextContent("Complexity");
    // No standalone <label> wrapping visible "Priority"/"Complexity" text —
    // the only place those words appear is inside each select's own
    // placeholder <option> (asserted above), never as a sibling text node.
    expect(document.querySelector("label")).toBeNull();
    expect(screen.queryByText("None")).toBeNull();
  });

  // Task 1: a small on-theme eyebrow (with a magnifying-glass icon) opens
  // its own row, ahead of search — "Muster" was renamed "Scry".
  it("shows the Scry eyebrow at the start of the row", () => {
    render(<FilterBar {...base} />);
    expect(screen.getByText("Scry")).toBeInTheDocument();
    expect(screen.queryByText("Muster")).not.toBeInTheDocument();
  });
});

// Task 2: the root element carries a stable id + the native `hidden`
// attribute driven by `filtersOpen` — its OWN independent toggle now (the
// "Filters ▾" button in TopBar), split from the old shared `controlsOpen`
// that used to also drive TopBar's `#topbar-controls-group`. Task 3: this
// takes effect on every viewport, not just ≤720px (see App.test.tsx/
// TopBar.test.tsx for the cross-component wiring; this is just the unit
// contract on FilterBar's own root element).
describe("<FilterBar/> Filters collapse wiring (Task 2/3)", () => {
  it("has a stable #filter-bar id for aria-controls to reference", () => {
    render(<FilterBar {...base} />);
    expect(document.getElementById("filter-bar")).not.toBeNull();
  });

  it("carries the native hidden attribute when filtersOpen is false", () => {
    render(<FilterBar {...base} filtersOpen={false} />);
    expect(document.getElementById("filter-bar")).not.toBeVisible();
  });

  it("is visible when filtersOpen is true", () => {
    render(<FilterBar {...base} filtersOpen={true} />);
    expect(document.getElementById("filter-bar")).toBeVisible();
  });
});
