import { labelColor } from "../board/labelColor";

export interface LabelChipsProps {
  labels: string[];
  /** Extra class(es) on the wrapper — e.g. a tile-specific vs. drawer-specific
   * layout tweak. Never applied to the individual chips themselves. */
  className?: string;
}

/**
 * Renders a card's `labels` (F1, WF-058) as small coloured chips — each
 * label's colour comes from `labelColor`'s stable curated-palette mapping
 * (board/labelColor.ts), NOT the F10 editable colour registry (WF-067,
 * deferred): no per-project colour configuration here, just a readable,
 * consistent swatch per label.
 *
 * Renders nothing at all (not even an empty wrapper) when `labels` is empty,
 * so a label-less card's tile/drawer layout is byte-identical to before this
 * component existed — see TileShell/CardDetailDrawer call sites.
 */
function LabelChips({ labels, className }: LabelChipsProps) {
  // Defensive guard: the contract guarantees `labels` is always present, but
  // treat a missing/undefined value as `[]` rather than crashing.
  const list = labels ?? [];
  if (list.length === 0) return null;

  return (
    <div className={"label-chips" + (className ? ` ${className}` : "")}>
      {list.map((label) => (
        <span
          key={label}
          className={`label-chip label-chip--${labelColor(label)}`}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

export default LabelChips;
