import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ChecklistRows from "./ChecklistRows";
import type { ChecklistEntry } from "../board/checklistWindow";

function entry(task: string, status: string): ChecklistEntry {
  return { task, subject: `Subject ${task}`, status };
}

describe("<ChecklistRows/>", () => {
  it("renders one <li> per entry with its subject text", () => {
    render(
      <ChecklistRows entries={[entry("1", "pending"), entry("2", "completed")]} />
    );
    expect(screen.getByText("Subject 1")).toBeInTheDocument();
    expect(screen.getByText("Subject 2")).toBeInTheDocument();
  });

  it("buckets a recognised status to its own row class", () => {
    render(<ChecklistRows entries={[entry("1", "in_progress")]} />);
    const row = screen.getByText("Subject 1").closest("li");
    expect(row).toHaveClass("checklist__row--in_progress");
  });

  it("buckets ANY unrecognised status (incl. the literal string 'None') as pending", () => {
    render(
      <ChecklistRows
        entries={[entry("1", "None"), entry("2", "some-weird-status")]}
      />
    );
    expect(screen.getByText("Subject 1").closest("li")).toHaveClass(
      "checklist__row--pending"
    );
    expect(screen.getByText("Subject 2").closest("li")).toHaveClass(
      "checklist__row--pending"
    );
  });

  it("a completed row gets the completed (strikethrough) class and a check glyph", () => {
    render(<ChecklistRows entries={[entry("1", "completed")]} />);
    const row = screen.getByText("Subject 1").closest("li")!;
    expect(row).toHaveClass("checklist__row--completed");
    expect(row).toHaveTextContent("✓");
  });

  it("an in_progress row carries the bucket class the CSS pulse animation targets", () => {
    render(<ChecklistRows entries={[entry("1", "in_progress")]} />);
    const row = screen.getByText("Subject 1").closest("li")!;
    expect(row).toHaveClass("checklist__row--in_progress");
    expect(row).toHaveTextContent("●");
  });

  it("a pending row shows the open-circle glyph", () => {
    render(<ChecklistRows entries={[entry("1", "pending")]} />);
    const row = screen.getByText("Subject 1").closest("li")!;
    expect(row).toHaveTextContent("○");
  });

  it("renders NO interactive element — inert tile content", () => {
    const { container } = render(
      <ChecklistRows
        entries={[
          entry("1", "pending"),
          entry("2", "in_progress"),
          entry("3", "completed"),
        ]}
      />
    );
    expect(
      container.querySelectorAll('button, a, [role="button"], [role]').length
    ).toBe(0);
  });

  it('windowed=true applies the edge-fade container class', () => {
    const { container } = render(
      <ChecklistRows entries={[entry("1", "pending")]} windowed />
    );
    const list = container.querySelector("ul")!;
    expect(list).toHaveClass("checklist");
    expect(list).toHaveClass("checklist--windowed");
  });

  it("windowed omitted (drawer/full-list mode) does NOT apply the edge-fade class", () => {
    const { container } = render(
      <ChecklistRows entries={[entry("1", "pending")]} />
    );
    const list = container.querySelector("ul")!;
    expect(list).toHaveClass("checklist");
    expect(list).not.toHaveClass("checklist--windowed");
  });

  it("does NOT mark any row as newly-appeared on first mount", () => {
    render(
      <ChecklistRows entries={[entry("1", "pending"), entry("2", "pending")]} />
    );
    expect(screen.getByText("Subject 1").closest("li")).not.toHaveClass(
      "checklist__row--appear"
    );
    expect(screen.getByText("Subject 2").closest("li")).not.toHaveClass(
      "checklist__row--appear"
    );
  });

  it("marks a row whose task id is new since the last render with the appear class, leaving prior rows alone", () => {
    const { rerender } = render(
      <ChecklistRows entries={[entry("1", "pending")]} />
    );
    expect(screen.getByText("Subject 1").closest("li")).not.toHaveClass(
      "checklist__row--appear"
    );

    rerender(
      <ChecklistRows
        entries={[entry("1", "pending"), entry("2", "in_progress")]}
      />
    );

    expect(screen.getByText("Subject 1").closest("li")).not.toHaveClass(
      "checklist__row--appear"
    );
    expect(screen.getByText("Subject 2").closest("li")).toHaveClass(
      "checklist__row--appear"
    );
  });

  it("a row present across two renders loses its appear class on the render after it appeared", () => {
    const { rerender } = render(
      <ChecklistRows entries={[entry("1", "pending")]} />
    );
    rerender(
      <ChecklistRows
        entries={[entry("1", "pending"), entry("2", "pending")]}
      />
    );
    expect(screen.getByText("Subject 2").closest("li")).toHaveClass(
      "checklist__row--appear"
    );

    // A third render with the SAME entries: "2" is no longer new.
    rerender(
      <ChecklistRows
        entries={[entry("1", "pending"), entry("2", "pending")]}
      />
    );
    expect(screen.getByText("Subject 2").closest("li")).not.toHaveClass(
      "checklist__row--appear"
    );
  });
});
