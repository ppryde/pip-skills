import { describe, expect, it } from "vitest";
import { checklistWindow } from "./checklistWindow";
import type { ChecklistEntry } from "./checklistWindow";

function entry(task: string, status: string): ChecklistEntry {
  return { task, subject: `Subject ${task}`, status };
}

describe("checklistWindow", () => {
  it("empty list -> empty window, null activeIndex", () => {
    expect(checklistWindow([])).toEqual({ visible: [], activeIndex: null });
  });

  it("active = the first in_progress entry", () => {
    const entries = [
      entry("1", "completed"),
      entry("2", "in_progress"),
      entry("3", "pending"),
      entry("4", "in_progress"),
    ];
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible).toEqual(entries);
    expect(visible[activeIndex!].task).toBe("2");
  });

  it("no in_progress -> active = first non-completed entry", () => {
    const entries = [
      entry("1", "completed"),
      entry("2", "completed"),
      entry("3", "pending"),
      entry("4", "pending"),
    ];
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible[activeIndex!].task).toBe("3");
  });

  it("all completed -> active = the last entry", () => {
    const entries = [entry("1", "completed"), entry("2", "completed"), entry("3", "completed")];
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible[activeIndex!].task).toBe("3");
  });

  it("a list <= max is returned whole, activeIndex mapped to its position", () => {
    const entries = [entry("1", "completed"), entry("2", "in_progress"), entry("3", "pending")];
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible).toEqual(entries);
    expect(activeIndex).toBe(1);
  });

  it("windows a long list, centred on the active entry", () => {
    // 11 entries, active = index 5 (task "6"), max 5 -> half=2, start=3.
    const entries = Array.from({ length: 11 }, (_, i) =>
      entry(String(i + 1), i === 5 ? "in_progress" : "completed")
    );
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible.map((e) => e.task)).toEqual(["4", "5", "6", "7", "8"]);
    expect(activeIndex).toBe(2);
    expect(visible[activeIndex!].task).toBe("6");
  });

  it("clamps the window to the START of the list when active is near the front", () => {
    // active at index 1, half=2 -> naive start = -1, clamps to 0.
    const entries = Array.from({ length: 11 }, (_, i) =>
      entry(String(i + 1), i === 1 ? "in_progress" : "completed")
    );
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible.map((e) => e.task)).toEqual(["1", "2", "3", "4", "5"]);
    expect(activeIndex).toBe(1);
  });

  it("clamps the window to the END of the list when active is near the back", () => {
    // 11 entries, active at index 9, half=2 -> naive start = 7, entries.length-max=6 -> min(7,6)=6.
    const entries = Array.from({ length: 11 }, (_, i) =>
      entry(String(i + 1), i === 9 ? "in_progress" : "completed")
    );
    const { visible, activeIndex } = checklistWindow(entries, 5);
    expect(visible.map((e) => e.task)).toEqual(["7", "8", "9", "10", "11"]);
    expect(activeIndex).toBe(3);
  });

  it("respects a custom max", () => {
    const entries = Array.from({ length: 6 }, (_, i) => entry(String(i + 1), "pending"));
    const { visible, activeIndex } = checklistWindow(entries, 3);
    expect(visible.length).toBe(3);
    expect(activeIndex).not.toBeNull();
  });
});
