/** A stat tile: sentence-case label, compact value, optional footnote. The
 * value is the loud element; everything else is muted ink. */
export interface StatTileProps {
  label: string;
  value: string;
  note?: string;
  /** CSS custom-property name for the tile's accent rule. Decorative only —
   * it groups a tile with the chart sharing its measure, never a value. */
  hue?: string;
}

export default function StatTile({ label, value, note, hue = "--chr-context" }: StatTileProps) {
  return (
    <div className="chr-tile" style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <span className="chr-tile__label">{label}</span>
      <span className="chr-tile__value">{value}</span>
      {note && <span className="chr-tile__note">{note}</span>}
    </div>
  );
}
