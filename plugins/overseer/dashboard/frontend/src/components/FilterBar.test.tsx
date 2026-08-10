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
  onClear: () => {},
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

  it("choosing a priority calls onPriority with the value (null for None)", () => {
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

  it("choosing a complexity calls onComplexity with the value (null for None)", () => {
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
    expect(screen.getByRole("button", { name: /clear filters/i })).toBeDisabled();
  });

  it("enables Clear and calls onClear when not default", () => {
    const onClear = vi.fn();
    render(<FilterBar {...base} isDefault={false} onClear={onClear} />);
    const clearBtn = screen.getByRole("button", { name: /clear filters/i });
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
});
