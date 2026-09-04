import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BarList, ColumnChart, LineChart } from "./ChronicleCharts";

const fmt = (n: number) => String(n);

describe("<ColumnChart/>", () => {
  it("draws one bar per non-zero point and a table-view twin", () => {
    render(
      <ColumnChart
        title="Tokens per day"
        format={fmt}
        points={[
          { label: "1 Sep", detail: "2026-09-01", value: 10 },
          { label: "2 Sep", detail: "2026-09-02", value: 0 },
          { label: "3 Sep", detail: "2026-09-03", value: 25 },
        ]}
      />
    );
    expect(screen.getAllByTestId("chr-bar")).toHaveLength(2);
    expect(screen.getByRole("img", { name: "Tokens per day" })).toBeInTheDocument();
    expect(screen.getByText("Table view")).toBeInTheDocument();
    expect(screen.getByText("2026-09-02")).toBeInTheDocument();
  });

  it("shows a tooltip for the hovered slot", () => {
    render(
      <ColumnChart title="T" format={fmt} points={[{ label: "a", value: 3 }, { label: "b", value: 7 }]} />
    );
    fireEvent.mouseEnter(screen.getByLabelText("b: 7"));
    expect(screen.getByRole("status")).toHaveTextContent("7");
  });

  it("renders an empty note without data", () => {
    render(<ColumnChart title="T" format={fmt} points={[]} />);
    expect(screen.getByText(/no data/i)).toBeInTheDocument();
  });
});

describe("<BarList/>", () => {
  it("scales fills against the largest row", () => {
    render(
      <BarList title="Tools" format={fmt} rows={[{ label: "Bash", value: 50 }, { label: "Read", value: 25 }]} />
    );
    const fills = screen.getAllByTestId("chr-barlist-fill");
    expect(fills[0]).toHaveStyle({ width: "100%" });
    expect(fills[1]).toHaveStyle({ width: "50%" });
    expect(screen.getByText("Bash")).toBeInTheDocument();
  });
});

describe("<LineChart/>", () => {
  it("draws the series and compaction markers", () => {
    render(<LineChart title="Context" format={fmt} values={[100, 200, 50, 120]} markers={[2]} />);
    expect(screen.getByTestId("chr-line")).toBeInTheDocument();
    expect(screen.getAllByTestId("chr-marker")).toHaveLength(1);
    expect(screen.getByText("turn 3")).toBeInTheDocument();
  });
});
