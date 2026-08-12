import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Input, { Textarea } from "./Input";

describe("<Input/>", () => {
  it("renders a .qb-input and forwards value/onChange", () => {
    const onChange = vi.fn();
    render(
      <Input aria-label="Search" value="quest" onChange={onChange} />
    );
    const input = screen.getByRole("textbox", { name: "Search" });
    expect(input).toHaveClass("qb-input");
    expect(input).toHaveValue("quest");
    fireEvent.change(input, { target: { value: "quest2" } });
    expect(onChange).toHaveBeenCalled();
  });
});

describe("<Textarea/>", () => {
  it("renders a .qb-input textarea and forwards props", () => {
    render(<Textarea aria-label="Body" rows={4} value="hello" onChange={() => {}} />);
    const textarea = screen.getByRole("textbox", { name: "Body" });
    expect(textarea.tagName).toBe("TEXTAREA");
    expect(textarea).toHaveClass("qb-input");
    expect(textarea).toHaveAttribute("rows", "4");
  });
});
