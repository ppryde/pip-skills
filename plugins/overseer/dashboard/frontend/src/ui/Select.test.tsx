import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Select from "./Select";

describe("<Select/>", () => {
  it("renders a .qb-select and forwards children options", () => {
    render(
      <Select aria-label="Example" value="a" onChange={() => {}}>
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>
    );
    const select = screen.getByRole("combobox", { name: "Example" });
    expect(select).toHaveClass("qb-select");
    expect(screen.getByRole("option", { name: "A" })).toBeInTheDocument();
  });

  it("renders an optional label via .qb-label", () => {
    render(
      <Select label="Repo" aria-label="Repo" value="a" onChange={() => {}}>
        <option value="a">A</option>
      </Select>
    );
    const label = screen.getByText("Repo");
    expect(label).toHaveClass("qb-label");
  });

  it("forwards onChange", () => {
    const onChange = vi.fn();
    render(
      <Select aria-label="Example" value="a" onChange={onChange}>
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Example" }), {
      target: { value: "b" },
    });
    expect(onChange).toHaveBeenCalled();
  });
});
