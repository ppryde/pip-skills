import { labelColor } from "../board/labelColor";

export interface LabelChipsProps {
  labels: string[];
  /** Extra class(es) on the wrapper — e.g. a tile-specific vs. drawer-specific
   * layout tweak. Never applied to the individual chips themselves. */
  className?: string;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`.
   * When a label has a registry entry, its chosen key wins over
   * `labelColor`'s hash-palette fallback. Omitted entirely (undefined) is
   * indistinguishable from `{}` — both mean "no overrides", same as before
   * this prop existed. */
  colorRegistry?: Record<string, string>;
}

/**
 * Renders a card's `labels` (F1, WF-058) as small coloured chips. Each
 * label's colour comes from `labelColor`, which prefers the F10 editable
 * colour registry (WF-067) — `colorRegistry`, threaded from the board
 * payload's `label_colors` — falling back to the stable curated-palette hash
 * (board/labelColor.ts) for any label with no registry entry.
 *
 * Renders nothing at all (not even an empty wrapper) when `labels` is empty,
 * so a label-less card's tile/drawer layout is byte-identical to before this
 * component existed — see TileShell/CardDetailDrawer call sites.
 */
function LabelChips({ labels, className, colorRegistry }: LabelChipsProps) {
  // Defensive guard: the contract guarantees `labels` is always present, but
  // treat a missing/undefined value as `[]` rather than crashing.
  const list = labels ?? [];
  if (list.length === 0) return null;

  return (
    <div className={"label-chips" + (className ? ` ${className}` : "")}>
      {list.map((label) => (
        <span
          key={label}
          className={`label-chip label-chip--${labelColor(label, colorRegistry)}`}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

export default LabelChips;
