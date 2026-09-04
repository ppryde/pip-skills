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

  it("caps the plotted bars on a long series but keeps every row in the table", () => {
    // 150 same-label days: exercises both the MAX_POINTS cap (a full year+
    // of "All time" daily points would otherwise smear into unreadable
    // slivers) and the key-collision case a bare display-label key hits
    // once the year is stripped from the label.
    const points = Array.from({ length: 150 }, (_, i) => ({
      label: "4 Sep",
      detail: `2026-${String((i % 12) + 1).padStart(2, "0")}-04`,
      value: i,
    }));
    render(<ColumnChart title="Long series" format={fmt} points={points} />);
    // Rendered points are the last 120 (indices 30-149, all value > 0), so
    // every one draws a bar.
    expect(screen.getAllByTestId("chr-bar")).toHaveLength(120);
    expect(screen.getByText(/most recent 120 of 150/)).toBeInTheDocument();
    // The table view twin is never capped — every point is still reachable.
    const table = screen.getByText("Table view").closest("details");
    expect(table?.querySelectorAll("tbody tr")).toHaveLength(150);
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
  it("draws the series, compaction markers and cold rings", () => {
    render(
      <LineChart
        title="Context"
        format={fmt}
        values={[100, 200, 50, 120]}
        markers={[2]}
        dots={[0, 2, 99]}
        annotate={(i) => (i === 0 ? "cold" : null)}
      />
    );
    expect(screen.getByTestId("chr-line")).toBeInTheDocument();
    expect(screen.getAllByTestId("chr-marker")).toHaveLength(1);
    expect(screen.getAllByTestId("chr-ring")).toHaveLength(2); // out-of-range 99 dropped
    expect(screen.getByText("turn 1 (cold)")).toBeInTheDocument();
    expect(screen.getByText("turn 3")).toBeInTheDocument();
  });
});
