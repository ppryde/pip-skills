import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import BeastFace from "./BeastFace";

describe("<BeastFace/>", () => {
  it("renders dot eyes and a grumpy mouth (with teeth) while alive", () => {
    const { container } = render(<BeastFace hue="#5c86b0" horns={false} slain={false} />);
    expect(container.querySelectorAll(".beast-face__eye--dot").length).toBe(2);
    expect(container.querySelectorAll(".beast-face__eye--x").length).toBe(0);
    expect(container.querySelector(".beast-face__mouth--grumpy")).toBeInTheDocument();
    expect(container.querySelector(".beast-face__mouth--smile")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".beast-face__tooth").length).toBe(2);
  });

  it("renders X eyes and a smile, no teeth, once slain", () => {
    const { container } = render(<BeastFace hue="#5c86b0" horns={false} slain={true} />);
    expect(container.querySelectorAll(".beast-face__eye--x").length).toBe(2);
    expect(container.querySelectorAll(".beast-face__eye--dot").length).toBe(0);
    expect(container.querySelector(".beast-face__mouth--smile")).toBeInTheDocument();
    expect(container.querySelector(".beast-face__mouth--grumpy")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".beast-face__tooth").length).toBe(0);
  });

  it("renders horn paths when horns is true", () => {
    const { container } = render(<BeastFace hue="#5c86b0" horns={true} slain={false} />);
    expect(container.querySelectorAll(".beast-face__horn").length).toBe(2);
    expect(container.querySelectorAll(".beast-face__brow").length).toBe(0);
  });

  it("renders brow paths instead of horns when horns is false", () => {
    const { container } = render(<BeastFace hue="#5c86b0" horns={false} slain={false} />);
    expect(container.querySelectorAll(".beast-face__horn").length).toBe(0);
    expect(container.querySelectorAll(".beast-face__brow").length).toBe(1);
  });

  it("fills the ellipse with the given hue and never hard-codes the outline colour", () => {
    const { container } = render(<BeastFace hue="#d98a3d" horns={false} slain={false} />);
    const ellipse = container.querySelector("ellipse");
    expect(ellipse).toHaveAttribute("fill", "#d98a3d");
    expect(ellipse).toHaveAttribute("stroke", "var(--qb-beast-ink)");
    const svgMarkup = container.querySelector("svg")!.outerHTML;
    expect(svgMarkup).not.toContain("#2c2015");
    expect(svgMarkup).not.toContain("#2C2015");
  });

  // impl-review finding: the eye/mouth/teeth cream highlight was hard-coded
  // to the literal #f6ead2 in eight places (both slain and alive branches)
  // instead of referencing styles.css's --qb-party-text token, which is
  // the byte-identical hex — a KB-007 violation same in spirit as the
  // outline check above, just for the second colour this component paints.
  it("never hard-codes the eye/mouth cream highlight — uses var(--qb-party-text) in both alive and slain states", () => {
    const alive = render(<BeastFace hue="#5c86b0" horns={true} slain={false} />);
    const aliveMarkup = alive.container.querySelector("svg")!.outerHTML;
    expect(aliveMarkup).not.toContain("#f6ead2");
    expect(aliveMarkup).not.toContain("#F6EAD2");
    expect(aliveMarkup).toContain("var(--qb-party-text)");

    const slain = render(<BeastFace hue="#5c86b0" horns={true} slain={true} />);
    const slainMarkup = slain.container.querySelector("svg")!.outerHTML;
    expect(slainMarkup).not.toContain("#f6ead2");
    expect(slainMarkup).not.toContain("#F6EAD2");
    expect(slainMarkup).toContain("var(--qb-party-text)");
  });

  it("rotates the ellipse -3deg around its own centre, per the design reference", () => {
    const { container } = render(<BeastFace hue="#5c86b0" horns={false} slain={false} />);
    expect(container.querySelector("ellipse")).toHaveAttribute("transform", "rotate(-3 25 25)");
  });
});
