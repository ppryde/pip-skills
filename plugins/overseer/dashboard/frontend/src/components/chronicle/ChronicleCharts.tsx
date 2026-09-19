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
import { useId, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { formatDay, formatTokens, formatUsd, formatWhen, niceTicks } from "../../board/chronicle/format";
import type { ChronicleLimitEvent, ChronicleLimitKind } from "../../api/types";

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
// A day-per-bar chart is 468px of plot at the default width; past this many
// points a bar is under 4px and the columns smear into an unreadable block
// (an "All time" window can be years of daily points). Window to the most
// recent MAX_POINTS and say so — the Table view twin below is never capped,
// so no data is lost, only what the plot itself renders.
const MAX_POINTS = 120;

function TableView({
  title,
  rows,
  extraHeading,
}: {
  title: string;
  rows: { label: string; value: string; extra?: string }[];
  /** Heading for an optional third column (`row.extra`), e.g. a per-turn
   * gap beside a per-turn value. */
  extraHeading?: string;
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
            {extraHeading && <th scope="col">{extraHeading}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            // Index-qualified for the same reason as ColumnChart's plotted
            // points: `row.label` is `p.detail ?? p.label`, which repeats
            // whenever two points land on the same day/name.
            <tr key={`${i}-${row.label}`}>
              <td>{row.label}</td>
              <td className="chr-num">{row.value}</td>
              {extraHeading && <td className="chr-num">{row.extra ?? "—"}</td>}
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
  const capped = points.length > MAX_POINTS;
  const rendered = capped ? points.slice(-MAX_POINTS) : points;
  const max = Math.max(0, ...rendered.map((p) => p.value));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const slot = rendered.length > 0 ? plotW / rendered.length : plotW;
  const bar = Math.min(MAX_BAR, Math.max(2, slot - 2));
  const stride = labelStride(rendered.length, plotW);
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
        {rendered.map((p, i) => {
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
          // Keyed on index + detail, not the bare display label: per-day
          // labels drop the year ("4 Sep"), so a multi-year "All time"
          // window can repeat a label and collide on label-only keys.
          return (
            <g key={`${i}-${p.detail ?? p.label}`}>
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
      {hover !== null && rendered[hover] && (
        <Tooltip
          x={`${((MARGIN.left + slot * hover + slot / 2) / width) * 100}%` as unknown as number}
          y={0}
        >
          <strong>{format(rendered[hover].value)}</strong>
          <span>{rendered[hover].detail ?? rendered[hover].label}</span>
        </Tooltip>
      )}
      {capped && (
        <p className="chr-chart__note">
          Showing the most recent {MAX_POINTS} of {points.length} points — see Table view for the
          full history.
        </p>
      )}
      <TableView
        title={title}
        rows={points.map((p) => ({ label: p.detail ?? p.label, value: format(p.value) }))}
      />
    </div>
  );
}

export interface BarRow {
  label: string;
  value: number;
  detail?: string;
  /** React key, when the label is not unique. File rows shorten a path to
   * its last two segments, so `src/styles.css` names three different files —
   * duplicate keys leave React unable to remove the old rows, and switching
   * away from Files stranded them among the next list. Anything with a
   * genuinely unique label may omit it. */
  id?: string;
}

interface BarListProps {
  rows: BarRow[];
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
        <div className="chr-barlist__row" role="listitem" key={row.id ?? row.label} title={row.detail}>
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

export interface DonutSegment {
  label: string;
  value: number;
}

interface DonutProps {
  /** Two or three parts of one whole, in the order they should be drawn
   * (clockwise from twelve). Zero-valued parts are kept in the legend and
   * table but draw nothing. */
  segments: DonutSegment[];
  format: (n: number) => string;
  title: string;
  /** Figure in the ring's centre: the whole, and what it is. */
  centre: { value: string; label: string };
  hue?: string;
}

const DONUT_R = 44;
const DONUT_C = 60;
const DONUT_STROKE = 14;
const DONUT_LEN = 2 * Math.PI * DONUT_R;
// Surface gap between adjacent segments (the chart-guidance 2px spacer),
// in viewBox units of the 120-wide ring.
const DONUT_GAP = 2;

/** A part-to-whole ring for a two- or three-way split of ONE measure. The
 * parts are steps of the measure's own hue (darkest first), never separate
 * hues: the reader is meant to see "how much of the cache was the 1h kind",
 * not two rival categories. The whole sits in the centre as a hero figure
 * so the ring never has to be read for its total, and every part is
 * direct-labelled with its value and share beside it, so nothing rests on
 * the arc lengths or the colour steps alone. */
export function Donut({ segments, format, title, centre, hue = "--chr-context" }: DonutProps) {
  const id = useId();
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.value), 0);
  if (total <= 0) {
    return <p className="chr-chart__empty">No data in this window.</p>;
  }
  // A zero segment draws no arc but keeps its legend row — so an arc's colour
  // step is its index in `segments` (what the legend swatch uses), never its
  // index among the arcs actually drawn.
  const drawn = segments.map((s, step) => ({ s, step })).filter(({ s }) => s.value > 0);
  let offset = 0;
  const arcs = drawn.map(({ s, step }) => {
    const len = (s.value / total) * DONUT_LEN;
    // Trim each end by half the gap so neighbours never touch; a lone
    // segment is a full ring and needs no trim.
    const trim = drawn.length > 1 ? DONUT_GAP / 2 : 0;
    const dash = Math.max(0, len - trim * 2);
    const arc = { key: `${step}-${s.label}`, dash, start: offset + trim, step };
    offset += len;
    return arc;
  });
  const pct = (n: number) => `${Math.round((n / total) * 100)}%`;
  return (
    <div className="chr-donut" style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <svg
        viewBox="0 0 120 120"
        className="chr-donut__svg"
        role="img"
        aria-labelledby={`${id}-title`}
      >
        <title id={`${id}-title`}>{title}</title>
        <circle cx={DONUT_C} cy={DONUT_C} r={DONUT_R} className="chr-donut__track" strokeWidth={DONUT_STROKE} fill="none" />
        {arcs.map((a) => (
          <circle
            key={a.key}
            cx={DONUT_C}
            cy={DONUT_C}
            r={DONUT_R}
            className={`chr-donut__seg chr-donut__seg--${Math.min(3, a.step + 1)}`}
            strokeWidth={DONUT_STROKE}
            fill="none"
            strokeDasharray={`${a.dash} ${DONUT_LEN}`}
            strokeDashoffset={-a.start}
            transform={`rotate(-90 ${DONUT_C} ${DONUT_C})`}
            data-testid="chr-donut-seg"
          />
        ))}
        <text x={DONUT_C} y={DONUT_C - 1} className="chr-donut__centre-value" textAnchor="middle">
          {centre.value}
        </text>
        <text x={DONUT_C} y={DONUT_C + 13} className="chr-donut__centre-label" textAnchor="middle">
          {centre.label}
        </text>
      </svg>
      <ul className="chr-donut__legend" aria-label={`${title} breakdown`}>
        {segments.map((s, i) => (
          <li key={`${i}-${s.label}`} className="chr-donut__row">
            <span className={`chr-donut__swatch chr-donut__swatch--${Math.min(3, i + 1)}`} aria-hidden="true" />
            <span className="chr-donut__label">{s.label}</span>
            <span className="chr-donut__value chr-num">{format(s.value)}</span>
            <span className="chr-donut__pct chr-num">{pct(Math.max(0, s.value))}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Something notable that happened at one x index of a LineChart, drawn as a
 * small glyph on the plot and named in the legend beneath it. */
export type ChartEventKind = "cold" | "jump" | "compaction";

export interface ChartEvent {
  index: number;
  kind: ChartEventKind;
}

/** Glyph vocabulary, in legend order. Each is a 16×16 stroke drawing kept
 * on one visual weight so the three read as a set: an ice cube for a cold
 * cache turn, a peak for the biggest jump, an hourglass on the compaction
 * hairline. Never emoji: these scale and recolour with the chart. (An idle-
 * gap mark was tried and dropped — noisy, and the gap is in the tooltip.) */
const EVENT_KINDS: Record<ChartEventKind, { label: string; path: string }> = {
  cold: {
    label: "cold cache turn",
    // An isometric cube: front face, top face, right face, plus a glint.
    path: "M3 6 L3 13 L10 13 L10 6 Z M3 6 L6 3 L13 3 L10 6 M10 13 L13 10 L13 3 M5 8 L5 10",
  },
  jump: {
    label: "biggest jump",
    path: "M2 13 L6.5 5 L9.5 9.5 L11.5 7 L14 13 Z",
  },
  compaction: {
    label: "compaction",
    path: "M4 2.5 H12 L8 8 L12 13.5 H4 L8 8 Z",
  },
};

const EVENT_ORDER: ChartEventKind[] = ["cold", "jump", "compaction"];
const GLYPH = 14;
// Glyphs hover just above the line rather than sitting on it, so the point
// they mark stays visible beneath them.
const GLYPH_LIFT = 5;

interface LineChartProps {
  /** y per x index (turn n). */
  values: number[];
  format: (n: number) => string;
  title: string;
  /** Notable turns, drawn as glyphs just above the line (compactions also
   * get a vertical hairline, since they are the moments the line drops).
   * Several events at one index stack upward. */
  events?: ChartEvent[];
  /** Extra tooltip line for point i (e.g. "cold · idle 12m"). */
  annotate?: (i: number) => string | null;
  /** An extra column in the table view, one cell per x index (null = "—"),
   * for a per-point figure the plot itself does not show — the drawer uses
   * it for the gap since the previous turn. */
  tableColumn?: { heading: string; cell: (i: number) => string | null };
  hue?: string;
  height?: number;
}

/** Single-series line with a 10% area wash and a crosshair tooltip that
 * snaps to the nearest x — the reader aims at a turn, never at the line. */
export function LineChart({
  values,
  format,
  title,
  events = [],
  annotate,
  tableColumn,
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
  const inRange = events.filter((e) => e.index >= 0 && e.index < values.length);
  // Glyphs at one index stack upward from the line, in legend order, so a
  // cold turn after an idle gap shows both without either hiding the other.
  const byIndex = new Map<number, ChartEvent[]>();
  for (const e of inRange) byIndex.set(e.index, [...(byIndex.get(e.index) ?? []), e]);
  const presentKinds = EVENT_ORDER.filter((k) => inRange.some((e) => e.kind === k));
  const symbolId = (kind: ChartEventKind) => `${id}-glyph-${kind}`;

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
        <defs>
          {presentKinds.map((k) => (
            <symbol key={k} id={symbolId(k)} viewBox="0 0 16 16">
              <path d={EVENT_KINDS[k].path} />
            </symbol>
          ))}
        </defs>
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
        {inRange
          .filter((e) => e.kind === "compaction")
          .map((e) => (
            <line
              key={`m${e.index}`}
              x1={x(e.index)}
              x2={x(e.index)}
              y1={MARGIN.top}
              y2={MARGIN.top + plotH}
              className="chr-chart__marker"
              data-testid="chr-marker"
            />
          ))}
        <path d={area} className="chr-chart__area" />
        <path d={path} className="chr-chart__line" data-testid="chr-line" />
        {[...byIndex.entries()].flatMap(([i, list]) =>
          [...list]
            .sort((a, b) => EVENT_ORDER.indexOf(a.kind) - EVENT_ORDER.indexOf(b.kind))
            .map((e, stack) => (
              <use
                key={`${e.kind}${i}`}
                href={`#${symbolId(e.kind)}`}
                x={x(i) - GLYPH / 2}
                y={y(values[i]) - GLYPH - GLYPH_LIFT - stack * (GLYPH + 2)}
                width={GLYPH}
                height={GLYPH}
                className={`chr-chart__glyph chr-chart__glyph--${e.kind}`}
                data-testid="chr-event"
                data-kind={e.kind}
                aria-label={`${EVENT_KINDS[e.kind].label} at turn ${i + 1}`}
              />
            ))
        )}
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
      {presentKinds.length > 0 && (
        <ul className="chr-chart__legend" aria-label="Marks">
          {presentKinds.map((k) => (
            <li key={k} className="chr-chart__legend-item">
              <svg viewBox="0 0 16 16" className={`chr-chart__legend-glyph chr-chart__glyph chr-chart__glyph--${k}`} aria-hidden="true">
                <path d={EVENT_KINDS[k].path} />
              </svg>
              <span>{EVENT_KINDS[k].label}</span>
            </li>
          ))}
        </ul>
      )}
      <TableView
        title={title}
        extraHeading={tableColumn?.heading}
        rows={values.map((v, i) => {
          const marks = (byIndex.get(i) ?? []).map((e) => EVENT_KINDS[e.kind].label);
          const note = [annotate?.(i), ...marks].filter(Boolean).join(" · ");
          return {
            label: `turn ${i + 1}${note ? ` (${note})` : ""}`,
            value: format(v),
            extra: tableColumn?.cell(i) ?? undefined,
          };
        })}
      />
    </div>
  );
}

/* --- usage-limit timeline --------------------------------------------------
 * "Limits hit": events over time, coloured by kind. A stacked column per day
 * (kinds are an IDENTITY, not a magnitude, so this is the one chart here that
 * breaks the single-hue rule) plus a detail table beneath — the same
 * pointer-optional twin every chart above gives its data.
 */

/** Label and hue for each kind, in the fixed stacking/legend order. One of
 * the seven measure hues per kind (`--chr-cost` for the money-shaped one),
 * reusing the page's existing ramp rather than inventing a new one. */
export const LIMIT_KIND_META: Record<ChronicleLimitKind, { label: string; hue: string }> = {
  session: { label: "Session (5h)", hue: "--chr-turns" },
  weekly: { label: "Weekly", hue: "--chr-peak" },
  monthly_spend: { label: "Monthly spend", hue: "--chr-cost" },
  model: { label: "Per-model", hue: "--chr-tools" },
  other: { label: "Other", hue: "--qb-ink-400" },
};

const LIMIT_KIND_ORDER: ChronicleLimitKind[] = ["session", "weekly", "monthly_spend", "model", "other"];

/** "2026-09-04" from an epoch, in the VIEWER's local zone — the same zone the
 * banner's own reset time was read in, and the convention `formatDay`
 * already renders. */
function dayKey(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

interface LimitsTimelineProps {
  events: ChronicleLimitEvent[];
  height?: number;
}

/** One stacked bar per day this window saw a hit, segmented by kind, with a
 * legend and an event-by-event table (kind, when, reset, sessions affected,
 * tokens burned) beneath — the detail a hover alone could never carry for
 * every event at once. */
export function LimitsTimeline({ events, height = 200 }: LimitsTimelineProps) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();
  const width = 520;
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;

  const { days, counts, presentKinds } = useMemo(() => {
    const byDay = new Map<string, Record<ChronicleLimitKind, number>>();
    const seen = new Set<ChronicleLimitKind>();
    for (const e of events) {
      if (e.hit_at === null) continue;
      const key = dayKey(e.hit_at);
      const row = byDay.get(key) ?? { session: 0, weekly: 0, monthly_spend: 0, model: 0, other: 0 };
      row[e.kind] += 1;
      byDay.set(key, row);
      seen.add(e.kind);
    }
    const sortedDays = [...byDay.keys()].sort();
    return {
      days: sortedDays,
      counts: sortedDays.map((d) => byDay.get(d)!),
      presentKinds: LIMIT_KIND_ORDER.filter((k) => seen.has(k)),
    };
  }, [events]);

  if (events.length === 0) {
    return <p className="chr-chart__empty">No limit hits in this window.</p>;
  }

  const totals = counts.map((row) => LIMIT_KIND_ORDER.reduce((sum, k) => sum + row[k], 0));
  const max = Math.max(0, ...totals);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const slot = days.length > 0 ? plotW / days.length : plotW;
  const bar = Math.min(MAX_BAR, Math.max(4, slot - 2));
  const stride = labelStride(days.length, plotW);
  const y = (v: number) => MARGIN.top + plotH - (v / top) * plotH;

  return (
    <div className="chr-chart chr-limits">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chr-chart__svg"
        role="img"
        aria-labelledby={`${id}-title`}
        onMouseLeave={() => setHover(null)}
      >
        <title id={`${id}-title`}>Usage-limit hits per day, by kind</title>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} className="chr-chart__grid" />
            <text x={MARGIN.left - 6} y={y(t) + 3} className="chr-chart__tick" textAnchor="end">
              {Math.round(t)}
            </text>
          </g>
        ))}
        {days.map((d, i) => {
          const cx = MARGIN.left + slot * i + slot / 2;
          const x0 = cx - bar / 2;
          let stacked = 0;
          return (
            <g key={d}>
              {LIMIT_KIND_ORDER.map((k) => {
                const v = counts[i][k];
                if (v === 0) return null;
                const yTop = y(stacked + v);
                const yBase = y(stacked);
                stacked += v;
                return (
                  <rect
                    key={k}
                    x={x0}
                    y={yTop}
                    width={bar}
                    height={Math.max(0, yBase - yTop)}
                    className={`chr-limits__seg chr-limits__seg--${k}${hover === i ? " chr-limits__seg--hover" : ""}`}
                    data-testid="chr-limits-seg"
                    data-kind={k}
                  />
                );
              })}
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
                aria-label={`${formatDay(d)}: ${LIMIT_KIND_ORDER.filter((k) => counts[i][k] > 0)
                  .map((k) => `${counts[i][k]} ${LIMIT_KIND_META[k].label}`)
                  .join(", ")}`}
              />
              {i % stride === 0 && (
                <text x={cx} y={height - 6} className="chr-chart__tick" textAnchor="middle">
                  {formatDay(d)}
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
      {hover !== null && (
        <Tooltip x={`${((MARGIN.left + slot * hover + slot / 2) / width) * 100}%` as unknown as number} y={0}>
          <strong>{formatDay(days[hover])}</strong>
          {LIMIT_KIND_ORDER.filter((k) => counts[hover][k] > 0).map((k) => (
            <span key={k}>
              {LIMIT_KIND_META[k].label}: {counts[hover][k]}
            </span>
          ))}
        </Tooltip>
      )}
      <ul className="chr-chart__legend" aria-label="Limit kinds">
        {presentKinds.map((k) => (
          <li key={k} className="chr-chart__legend-item">
            <span
              className={`chr-limits__swatch chr-limits__swatch--${k}`}
              aria-hidden="true"
            />
            <span>{LIMIT_KIND_META[k].label}</span>
          </li>
        ))}
      </ul>
      <details className="chr-chart__table">
        <summary>Table view</summary>
        <table className="chr-table chr-table--compact">
          <caption className="sr-only">Usage-limit hits</caption>
          <thead>
            <tr>
              <th scope="col">Kind</th>
              <th scope="col">Hit at</th>
              <th scope="col">Resets</th>
              <th scope="col" className="chr-num">Sessions</th>
              <th scope="col" className="chr-num">Tokens to limit</th>
              <th scope="col" className="chr-num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {[...events]
              .sort((a, b) => (b.hit_at ?? 0) - (a.hit_at ?? 0))
              .map((e, i) => (
                <tr key={`${i}-${e.hit_at ?? "?"}-${e.kind}`}>
                  <td>{LIMIT_KIND_META[e.kind].label}{e.model ? ` (${e.model})` : ""}</td>
                  <td>{formatWhen(e.hit_at)}</td>
                  <td>{e.reset_raw ?? "—"}</td>
                  <td className="chr-num">{e.sessions}</td>
                  <td className="chr-num">
                    {e.tokens_to_limit ? formatTokens(e.tokens_to_limit.total_tokens) : "—"}
                  </td>
                  <td className="chr-num">
                    {e.tokens_to_limit ? formatUsd(e.tokens_to_limit.cost_usd) : "—"}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
