import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SourceIcon from "./SourceIcon";

function markOf(container: HTMLElement): string | null {
  return container.querySelector(".almoner__source-icon")?.getAttribute("data-source") ?? null;
}

describe("SourceIcon", () => {
  it("draws a distinct mark per known service", () => {
    for (const source of ["slack", "linear", "mail", "almoner"]) {
      const { container } = render(<SourceIcon source={source} />);
      expect(markOf(container)).toBe(source);
    }
  });

  it("falls back to a mark for an unknown source rather than drawing nothing", () => {
    // A missing glyph would leave the badge a different height from its
    // neighbours, which reads as a rendering bug rather than a new source.
    const { container } = render(<SourceIcon source="telegram" />);
    expect(markOf(container)).toBe("unknown");
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("is decorative when it sits beside its own visible name", () => {
    // The badge already says "slack" in words; announcing it twice only pads
    // the row for a screen-reader user.
    const { container } = render(<SourceIcon source="slack" />);
    expect(container.querySelector(".almoner__source-icon")).toHaveAttribute(
      "aria-hidden", "true"
    );
  });

  it("is announced when it stands alone", () => {
    render(<SourceIcon source="slack" label="Slack" />);
    expect(screen.getByRole("img", { name: "Slack" })).toBeInTheDocument();
  });
});
