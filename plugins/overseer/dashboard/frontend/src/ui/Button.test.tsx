import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Button from "./Button";

describe("<Button/>", () => {
  it("renders a neutral .qb-btn by default", () => {
    render(<Button>Click me</Button>);
    const btn = screen.getByRole("button", { name: "Click me" });
    expect(btn).toHaveClass("qb-btn");
    expect(btn).not.toHaveClass("qb-btn--primary");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("adds qb-btn--primary for variant='primary'", () => {
    render(<Button variant="primary">Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass(
      "qb-btn",
      "qb-btn--primary"
    );
  });

  it("composes a caller-supplied className rather than replacing qb-btn", () => {
    render(<Button className="card-drawer__cancel-btn">Cancel</Button>);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass(
      "qb-btn",
      "card-drawer__cancel-btn"
    );
  });

  it("forwards onClick and disabled", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Disabled
      </Button>
    );
    const btn = screen.getByRole("button", { name: "Disabled" });
    expect(btn).toBeDisabled();
    btn.click();
    expect(onClick).not.toHaveBeenCalled();
  });
});
