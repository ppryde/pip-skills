import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DesignLibrary from "./DesignLibrary";

describe("<DesignLibrary/>", () => {
  it("renders every primitive group with its heading", () => {
    render(<DesignLibrary />);
    expect(
      screen.getByRole("heading", { name: /design library/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Buttons" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Selects" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chips" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Inputs" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Labels" })).toBeInTheDocument();
  });

  it("renders at least one live instance of each primitive", () => {
    render(<DesignLibrary />);
    expect(screen.getByRole("button", { name: "Primary" })).toHaveClass(
      "qb-btn--primary"
    );
    expect(
      screen.getByRole("combobox", { name: "Example choice" })
    ).toHaveClass("qb-select");
    expect(screen.getByText("7d window")).toHaveClass("qb-chip");
    expect(
      screen.getByRole("textbox", { name: "Example text input" })
    ).toHaveClass("qb-input");
    expect(screen.getByText("eyebrow label")).toHaveClass("qb-label");
  });
});
