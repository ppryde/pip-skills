/**
 * The Chronicle page's charts — hand-rolled inline SVG, no charting
 * dependency (the dashboard has none; every existing visual is SVG too).
 *
 * All three follow the same rules: one series per chart in one hue (the
 * data here is magnitude, not identity), thin marks with a rounded data-end,
 * hairline solid gridlines, text in ink tokens never the series colour, a
 * hover tooltip that never gates a value, and a `<details>` table view twin
 * under every plot so nothing is reachable by pointer alone.
 */
import { useId, useState } from "react";
import type { ReactNode } from "react";
import { niceTicks } from "../../board/chronicle/format";

export interface ChartPoint {
  /** Axis label (a day, a turn index). */
  label: string;
  value: number;
  /** Longer label for the tooltip/table; defaults to `label`. */
  detail?: string;
}

interface ColumnChartProps {
  points: ChartPoint[];
  /** Compact formatter for tooltips, the y-axis and the table. */
  format: (n: number) => string;
  /** Sentence-case name of the measure, used by the table view and the
   * accessible label ("Context tokens per day"). */
  title: string;
  /** CSS custom-property name supplying this chart's single hue. Each
   * MEASURE gets its own hue so the eye can tell the panels apart; within a
   * chart it stays one hue, because the data is magnitude, not identity. */
  hue?: string;
  height?: number;
}

const MARGIN = { top: 12, right: 8, bottom: 22, left: 44 };
const MAX_BAR = 24;

function TableView({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: string }[];
}) {
  return (
    <details className="chr-chart__table">
      <summary>Table view</summary>
      <table>
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr>
            <th scope="col">Label</th>
            <th scope="col">{title}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td className="chr-num">{row.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function Tooltip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div className="chr-chart__tooltip" style={{ left: x, top: y }} role="status">
      {children}
    </div>
  );
}

/** How many x labels fit: show every nth so ~48px is left per label. */
function labelStride(count: number, plotWidth: number): number {
  if (count === 0) return 1;
  return Math.max(1, Math.ceil(count / Math.max(1, Math.floor(plotWidth / 48))));
}

export function ColumnChart({
  points,
  format,
  title,
  hue = "--chr-context",
  height = 180,
}: ColumnChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();
  const width = 520;
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const max = Math.max(0, ...points.map((p) => p.value));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const slot = points.length > 0 ? plotW / points.length : plotW;
  const bar = Math.min(MAX_BAR, Math.max(2, slot - 2));
  const stride = labelStride(points.length, plotW);
  const y = (v: number) => MARGIN.top + plotH - (v / top) * plotH;

  if (points.length === 0) {
    return <p className="chr-chart__empty">No data in this window.</p>;
  }

  return (
    <div className="chr-chart" style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chr-chart__svg"
        role="img"
        aria-labelledby={`${id}-title`}
        onMouseLeave={() => setHover(null)}
      >
        <title id={`${id}-title`}>{title}</title>
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={MARGIN.left}
              x2={width - MARGIN.right}
              y1={y(t)}
              y2={y(t)}
              className="chr-chart__grid"
            />
            <text x={MARGIN.left - 6} y={y(t) + 3} className="chr-chart__tick" textAnchor="end">
              {format(t)}
            </text>
          </g>
        ))}
        {points.map((p, i) => {
          const cx = MARGIN.left + slot * i + slot / 2;
          const h = Math.max(0, (p.value / top) * plotH);
          const r = Math.min(4, bar / 2, h);
          const x0 = cx - bar / 2;
          const yTop = y(p.value);
          const base = MARGIN.top + plotH;
          // Rounded data-end, square at the baseline.
          const d =
            h === 0
              ? ""
              : `M${x0},${base} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x0 + bar - r} Q${x0 + bar},${yTop} ${x0 + bar},${yTop + r} V${base} Z`;
          return (
            <g key={p.label}>
              {d && (
                <path
                  d={d}
                  className={`chr-chart__bar${hover === i ? " chr-chart__bar--hover" : ""}`}
                  data-testid="chr-bar"
                />
              )}
              {/* Hit target: the whole slot, not the painted pixels. */}
              <rect
                x={MARGIN.left + slot * i}
                y={MARGIN.top}
                width={slot}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                aria-label={`${p.detail ?? p.label}: ${format(p.value)}`}
              />
              {i % stride === 0 && (
                <text x={cx} y={height - 6} className="chr-chart__tick" textAnchor="middle">
                  {p.label}
                </text>
              )}
            </g>
          );
        })}
        <line
          x1={MARGIN.left}
          x2={width - MARGIN.right}
          y1={MARGIN.top + plotH}
          y2={MARGIN.top + plotH}
          className="chr-chart__axis"
        />
      </svg>
      {hover !== null && points[hover] && (
        <Tooltip
          x={`${((MARGIN.left + slot * hover + slot / 2) / width) * 100}%` as unknown as number}
          y={0}
        >
          <strong>{format(points[hover].value)}</strong>
          <span>{points[hover].detail ?? points[hover].label}</span>
        </Tooltip>
      )}
      <TableView
        title={title}
        rows={points.map((p) => ({ label: p.detail ?? p.label, value: format(p.value) }))}
      />
    </div>
  );
}

interface BarListProps {
  rows: { label: string; value: number; detail?: string }[];
  format: (n: number) => string;
  title: string;
  hue?: string;
}

/** Horizontal bars for a ranked nominal list (models, tools). One hue: the
 * categories carry no order, so hue must not pretend they do. */
export function BarList({ rows, format, title, hue = "--chr-context" }: BarListProps) {
  if (rows.length === 0) {
    return <p className="chr-chart__empty">No data in this window.</p>;
  }
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div
      className="chr-barlist"
      role="list"
      aria-label={title}
      style={{ ["--chr-hue" as string]: `var(${hue})` }}
    >
      {rows.map((row) => (
        <div className="chr-barlist__row" role="listitem" key={row.label} title={row.detail}>
          <span className="chr-barlist__label">{row.label}</span>
          <span className="chr-barlist__track" aria-hidden="true">
            <span
              className="chr-barlist__fill"
              style={{ width: `${Math.max(1, (row.value / max) * 100)}%` }}
              data-testid="chr-barlist-fill"
            />
          </span>
          <span className="chr-barlist__value chr-num">{format(row.value)}</span>
        </div>
      ))}
    </div>
  );
}

interface LineChartProps {
  /** y per x index (turn n). */
  values: number[];
  format: (n: number) => string;
  title: string;
  /** x indices to mark with a vertical hairline (compactions). */
  markers?: number[];
  /** x indices to mark with a ring on the line (cold cache turns). */
  dots?: number[];
  /** Extra tooltip line for point i (e.g. "cold · idle 12m"). */
  annotate?: (i: number) => string | null;
  hue?: string;
  height?: number;
}

/** Single-series line with a 10% area wash and a crosshair tooltip that
 * snaps to the nearest x — the reader aims at a turn, never at the line. */
export function LineChart({
  values,
  format,
  title,
  markers = [],
  dots = [],
  annotate,
  hue = "--chr-context",
  height = 180,
}: LineChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();
  const width = 520;
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;
  if (values.length === 0) {
    return <p className="chr-chart__empty">No turns recorded.</p>;
  }
  const max = Math.max(0, ...values);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const x = (i: number) =>
    MARGIN.left + (values.length === 1 ? plotW / 2 : (i / (values.length - 1)) * plotW);
  const y = (v: number) => MARGIN.top + plotH - (v / top) * plotH;
  const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");
  const area = `${path} L${x(values.length - 1)},${MARGIN.top + plotH} L${x(0)},${MARGIN.top + plotH} Z`;
  const stride = labelStride(values.length, plotW);

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * width;
    const t = (px - MARGIN.left) / plotW;
    const i = Math.round(Math.min(1, Math.max(0, t)) * (values.length - 1));
    setHover(i);
  }

  return (
    <div className="chr-chart" style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chr-chart__svg"
        role="img"
        aria-labelledby={`${id}-title`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <title id={`${id}-title`}>{title}</title>
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={MARGIN.left}
              x2={width - MARGIN.right}
              y1={y(t)}
              y2={y(t)}
              className="chr-chart__grid"
            />
            <text x={MARGIN.left - 6} y={y(t) + 3} className="chr-chart__tick" textAnchor="end">
              {format(t)}
            </text>
          </g>
        ))}
        {markers.map((m) => (
          <line
            key={`m${m}`}
            x1={x(m)}
            x2={x(m)}
            y1={MARGIN.top}
            y2={MARGIN.top + plotH}
            className="chr-chart__marker"
            data-testid="chr-marker"
          />
        ))}
        <path d={area} className="chr-chart__area" />
        <path d={path} className="chr-chart__line" data-testid="chr-line" />
        {dots
          .filter((i) => i >= 0 && i < values.length)
          .map((i) => (
            <circle
              key={`d${i}`}
              cx={x(i)}
              cy={y(values[i])}
              r={4}
              className="chr-chart__ring"
              data-testid="chr-ring"
            />
          ))}
        {values.map((_, i) =>
          i % stride === 0 || i === values.length - 1 ? (
            <text
              key={`x${i}`}
              x={x(i)}
              y={height - 6}
              className="chr-chart__tick"
              textAnchor="middle"
            >
              {i + 1}
            </text>
          ) : null
        )}
        {hover !== null && (
          <g>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={MARGIN.top}
              y2={MARGIN.top + plotH}
              className="chr-chart__crosshair"
            />
            <circle cx={x(hover)} cy={y(values[hover])} r={5} className="chr-chart__dot" />
          </g>
        )}
        <line
          x1={MARGIN.left}
          x2={width - MARGIN.right}
          y1={MARGIN.top + plotH}
          y2={MARGIN.top + plotH}
          className="chr-chart__axis"
        />
      </svg>
      {hover !== null && (
        <Tooltip x={`${(x(hover) / width) * 100}%` as unknown as number} y={0}>
          <strong>{format(values[hover])}</strong>
          <span>turn {hover + 1}</span>
          {annotate?.(hover) && <span>{annotate(hover)}</span>}
        </Tooltip>
      )}
      <TableView
        title={title}
        rows={values.map((v, i) => {
          const note = annotate?.(i);
          return { label: `turn ${i + 1}${note ? ` (${note})` : ""}`, value: format(v) };
        })}
      />
    </div>
  );
}
