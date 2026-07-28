import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import BranchFilter from "./BranchFilter";

describe("<BranchFilter/>", () => {
  it("renders nothing when there are no distinct branches", () => {
    const { container } = render(
      <BranchFilter branches={[]} activeBranch={null} onSelect={() => {}} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders an 'All' option plus one per distinct branch", () => {
    render(
      <BranchFilter
        branches={["feat/a", "feat/b"]}
        activeBranch={null}
        onSelect={() => {}}
      />
    );
    expect(screen.getByLabelText("Branch")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "feat/a" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "feat/b" })).toBeInTheDocument();
  });

  it("defaults the select to 'All' when activeBranch is null", () => {
    render(
      <BranchFilter
        branches={["feat/a"]}
        activeBranch={null}
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Branch") as HTMLSelectElement).value).toBe("");
  });

  it("reflects activeBranch when it's a known branch", () => {
    render(
      <BranchFilter
        branches={["feat/a", "feat/b"]}
        activeBranch="feat/b"
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Branch") as HTMLSelectElement).value).toBe(
      "feat/b"
    );
  });

  it("falls back to 'All' when activeBranch names a branch no longer in the distinct set", () => {
    render(
      <BranchFilter
        branches={["feat/a"]}
        activeBranch="feat/stale"
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Branch") as HTMLSelectElement).value).toBe("");
  });

  it("calls onSelect with the chosen branch on change", () => {
    const onSelect = vi.fn();
    render(
      <BranchFilter
        branches={["feat/a", "feat/b"]}
        activeBranch={null}
        onSelect={onSelect}
      />
    );

    fireEvent.change(screen.getByLabelText("Branch"), {
      target: { value: "feat/b" },
    });

    expect(onSelect).toHaveBeenCalledWith("feat/b");
  });

  it("calls onSelect(null) when 'All' is chosen", () => {
    const onSelect = vi.fn();
    render(
      <BranchFilter
        branches={["feat/a"]}
        activeBranch="feat/a"
        onSelect={onSelect}
      />
    );

    fireEvent.change(screen.getByLabelText("Branch"), {
      target: { value: "" },
    });

    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
