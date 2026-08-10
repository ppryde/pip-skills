import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import LabelChips from "./LabelChips";
import { labelColor } from "../board/labelColor";

describe("LabelChips", () => {
  it("renders one chip per label, in order", () => {
    const { container } = render(
      <LabelChips labels={["policy", "architecture"]} />
    );
    const chips = container.querySelectorAll(".label-chip");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("policy");
    expect(chips[1]).toHaveTextContent("architecture");
  });

  it("renders nothing (no wrapper element) for an empty labels array", () => {
    const { container } = render(<LabelChips labels={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing and does not crash when labels is undefined", () => {
    const { container } = render(
      <LabelChips labels={undefined as unknown as string[]} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("gives each chip a colour class matching labelColor's stable mapping", () => {
    const { container } = render(<LabelChips labels={["policy"]} />);
    const chip = container.querySelector(".label-chip")!;
    expect(chip.className).toContain(`label-chip--${labelColor("policy")}`);
  });

  it("renders many labels without special-casing — wraps in CSS, not JS", () => {
    const many = Array.from({ length: 10 }, (_, i) => `label-${i}`);
    const { container } = render(<LabelChips labels={many} />);
    expect(container.querySelectorAll(".label-chip")).toHaveLength(10);
  });
});
