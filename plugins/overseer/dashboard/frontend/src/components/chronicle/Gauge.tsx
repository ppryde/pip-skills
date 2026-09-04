/**
 * A semicircular meter for a 0..1 ratio — the page's hero readout.
 *
 * The fill is the measure's own hue and the track a pale step of it (same
 * ramp, per the meter convention), so state reads across the whole arc. The
 * verdict word beside the value means the reading never rests on colour
 * alone, and the value is plain text, so nothing here is pointer-only.
 */
export interface GaugeProps {
  /** 0..1; null renders an empty arc and an em dash. */
  value: number | null;
  label: string;
  /** Rendered value, e.g. "97%". */
  display: string;
  /** Short word for where the reading sits ("warm", "mixed", "cold"). */
  verdict?: string;
  note?: string;
  /** CSS custom-property name supplying the fill hue. */
  hue?: string;
}

const R = 52;
const CX = 60;
const CY = 60;
const STROKE = 12;
// A semicircle from due west to due east.
const ARC_LENGTH = Math.PI * R;

export default function Gauge({
  value,
  label,
  display,
  verdict,
  note,
  hue = "--chr-cache",
}: GaugeProps) {
  const clamped = value === null ? 0 : Math.min(1, Math.max(0, value));
  const path = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;
  return (
    <div className="chr-gauge" style={{ ["--chr-gauge-hue" as string]: `var(${hue})` }}>
      <svg viewBox="0 0 120 74" className="chr-gauge__svg" role="img" aria-label={`${label}: ${display}`}>
        <path d={path} className="chr-gauge__track" strokeWidth={STROKE} fill="none" />
        <path
          d={path}
          className="chr-gauge__fill"
          strokeWidth={STROKE}
          fill="none"
          strokeDasharray={`${ARC_LENGTH * clamped} ${ARC_LENGTH}`}
          data-testid="chr-gauge-fill"
        />
      </svg>
      <span className="chr-gauge__value">{value === null ? "—" : display}</span>
      <span className="chr-gauge__label">{label}</span>
      {verdict && <span className="chr-gauge__verdict">{verdict}</span>}
      {note && <span className="chr-gauge__note">{note}</span>}
    </div>
  );
}
