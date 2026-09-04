/** A stat tile: sentence-case label, compact value, optional footnote. The
 * value is the loud element; everything else is muted ink. */
export interface StatTileProps {
  label: string;
  value: string;
  note?: string;
}

export default function StatTile({ label, value, note }: StatTileProps) {
  return (
    <div className="chr-tile">
      <span className="chr-tile__label">{label}</span>
      <span className="chr-tile__value">{value}</span>
      {note && <span className="chr-tile__note">{note}</span>}
    </div>
  );
}
