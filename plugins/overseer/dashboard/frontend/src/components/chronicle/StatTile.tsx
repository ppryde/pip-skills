import InfoTooltip from "../InfoTooltip";

/** A stat tile: sentence-case label, compact value, optional footnote. The
 * value is the loud element; everything else is muted ink. */
export interface StatTileProps {
  label: string;
  value: string;
  note?: string;
  /** CSS custom-property name for the tile's accent hue. Decorative only —
   * it groups a tile with the chart sharing its measure, never a value. */
  hue?: string;
  /** How the hue is worn. `tint` (default): a pale wash of it as the fill
   * and a stronger step as the border. `rule`: a plain parchment tile with
   * a 4px rule of the hue inset on the left. Both keep the same footprint. */
  accent?: "tint" | "rule";
  /** Explanation shown behind an InfoTooltip beside the label — for a tile
   * whose number needs a caveat (e.g. API-equivalent cost on a subscription
   * account) that a `note` footnote would otherwise have to spell out on
   * every render, tile density permitting or not. */
  labelInfo?: string;
}

export default function StatTile({
  label,
  value,
  note,
  hue = "--chr-context",
  labelInfo,
  accent = "tint",
}: StatTileProps) {
  return (
    <div className={`chr-tile chr-tile--${accent}`} style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <span className="chr-tile__label">
        {label}
        {labelInfo && (
          <InfoTooltip label={`About ${label}`} triggerClassName="chr-tile__info-trigger">
            {labelInfo}
          </InfoTooltip>
        )}
      </span>
      <span className="chr-tile__value">{value}</span>
      {note && <span className="chr-tile__note">{note}</span>}
    </div>
  );
}
