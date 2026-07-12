import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import MarkdownView from "./MarkdownView";

describe("MarkdownView", () => {
  it("renders bold, lists and GFM task-list checkboxes", () => {
    render(<MarkdownView text={"**bold**\n\n- item\n- [x] done task"} />);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("checkbox", { checked: true })).toBeDisabled();
  });

  it("never executes raw HTML in card text", () => {
    const { container } = render(
      <MarkdownView text={'<script>window.__pwned = true</script><img src=x onerror="x">'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("clamps headings inside .md-view", () => {
    const { container } = render(<MarkdownView text={"# Big"} />);
    expect(container.querySelector(".md-view h1")).not.toBeNull();
  });
});
