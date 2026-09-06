import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BarList, ColumnChart, Donut, LineChart } from "./ChronicleCharts";

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

describe("<Donut/>", () => {
  it("draws one arc per non-zero part, labels every part with value and share", () => {
    render(
      <Donut
        title="Cache written by TTL"
        format={fmt}
        centre={{ value: "200", label: "written" }}
        segments={[
          { label: "1h cache", value: 150 },
          { label: "5m cache", value: 50 },
          { label: "Unlabelled", value: 0 },
        ]}
      />
    );
    expect(screen.getByRole("img", { name: "Cache written by TTL" })).toBeInTheDocument();
    expect(screen.getAllByTestId("chr-donut-seg")).toHaveLength(2); // the zero part draws nothing
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("Unlabelled")).toBeInTheDocument(); // but stays in the legend
    expect(screen.getByText("written")).toBeInTheDocument();
  });

  it("keeps an arc's colour matched to its legend swatch across a zero part", () => {
    // The middle part draws no arc; the third part's arc must still wear
    // the THIRD colour (its legend swatch does), not slide into the second.
    render(
      <Donut
        title="T"
        format={fmt}
        centre={{ value: "10", label: "x" }}
        segments={[
          { label: "a", value: 5 },
          { label: "b", value: 0 },
          { label: "c", value: 5 },
        ]}
      />
    );
    const arcs = screen.getAllByTestId("chr-donut-seg");
    expect(arcs).toHaveLength(2);
    expect(arcs[1]).toHaveClass("chr-donut__seg--3");
    const swatch = screen.getByText("c").previousElementSibling;
    expect(swatch).toHaveClass("chr-donut__swatch--3");
  });

  it("renders an empty note when the whole is zero", () => {
    render(
      <Donut title="T" format={fmt} centre={{ value: "0", label: "x" }} segments={[{ label: "a", value: 0 }]} />
    );
    expect(screen.getByText(/no data/i)).toBeInTheDocument();
  });
});

describe("<LineChart/>", () => {
  it("draws the series and one glyph per event, with a legend and table notes", () => {
    render(
      <LineChart
        title="Context"
        format={fmt}
        values={[100, 200, 50, 120]}
        events={[
          { index: 2, kind: "compaction" },
          { index: 0, kind: "cold" },
          { index: 0, kind: "jump" },
          { index: 99, kind: "cold" },
        ]}
        annotate={(i) => (i === 0 ? "wrote 90 to cache · idle 11m" : null)}
      />
    );
    expect(screen.getByTestId("chr-line")).toBeInTheDocument();
    // A compaction is a hairline AND a glyph; the out-of-range event is dropped.
    expect(screen.getAllByTestId("chr-marker")).toHaveLength(1);
    const glyphs = screen.getAllByTestId("chr-event");
    expect(glyphs).toHaveLength(3);
    expect(glyphs.map((g) => g.getAttribute("data-kind")).sort()).toEqual(["cold", "compaction", "jump"]);
    // Two glyphs at turn 1 stack: the second sits higher than the first, and
    // both sit above the point they mark.
    const atOne = glyphs.filter((g) => g.getAttribute("aria-label")?.endsWith("at turn 1"));
    expect(atOne).toHaveLength(2);
    expect(Number(atOne[1].getAttribute("y"))).toBeLessThan(Number(atOne[0].getAttribute("y")));
    // Legend names only the kinds present, in a fixed order.
    const legend = screen.getByRole("list", { name: "Marks" });
    expect(legend).toHaveTextContent("cold cache turnbiggest jumpcompaction");
    // The table twin carries the marks as words, so nothing is glyph-only.
    expect(screen.getByText("turn 1 (wrote 90 to cache · idle 11m · cold cache turn · biggest jump)")).toBeInTheDocument();
    expect(screen.getByText("turn 3 (compaction)")).toBeInTheDocument();
  });

  it("adds an extra table column when asked, dashing the cells with nothing to say", () => {
    render(
      <LineChart
        title="Context"
        format={fmt}
        values={[100, 200, 50]}
        tableColumn={{ heading: "Since last turn", cell: (i) => (i === 0 ? null : `${i * 5}s`) }}
      />
    );
    const table = screen.getByText("Table view").closest("details")!;
    expect(table.querySelectorAll("thead th")[2]).toHaveTextContent("Since last turn");
    const cells = [...table.querySelectorAll("tbody tr")].map((r) => r.querySelectorAll("td")[2].textContent);
    expect(cells).toEqual(["—", "5s", "10s"]);
  });

  it("omits the legend when there are no events", () => {
    render(<LineChart title="Context" format={fmt} values={[1, 2]} />);
    expect(screen.queryByRole("list", { name: "Marks" })).not.toBeInTheDocument();
  });
});
