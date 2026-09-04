import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Gauge from "./Gauge";

describe("<Gauge/>", () => {
  it("fills the arc in proportion to the value", () => {
    render(<Gauge value={0.5} display="50%" label="Cache hit rate" verdict="cold" />);
    const fill = screen.getByTestId("chr-gauge-fill");
    const [drawn, total] = (fill.getAttribute("stroke-dasharray") ?? "").split(" ").map(Number);
    expect(drawn / total).toBeCloseTo(0.5, 5);
  });

  it("names the reading for assistive tech and in a word", () => {
    render(<Gauge value={0.97} display="97%" label="Cache hit rate" verdict="warm" note="12 cold turns" />);
    expect(screen.getByRole("img", { name: "Cache hit rate: 97%" })).toBeInTheDocument();
    expect(screen.getByText("warm")).toBeInTheDocument();
    expect(screen.getByText("12 cold turns")).toBeInTheDocument();
  });

  it("renders an empty arc and a dash with no value", () => {
    render(<Gauge value={null} display="—" label="Cache hit rate" />);
    const fill = screen.getByTestId("chr-gauge-fill");
    expect(fill.getAttribute("stroke-dasharray")?.startsWith("0 ")).toBe(true);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("clamps a value outside 0..1", () => {
    render(<Gauge value={1.4} display="140%" label="Peak" />);
    const fill = screen.getByTestId("chr-gauge-fill");
    const [drawn, total] = (fill.getAttribute("stroke-dasharray") ?? "").split(" ").map(Number);
    expect(drawn).toBeCloseTo(total, 5);
  });
});
