import { labelColor } from "../board/labelColor";
import { Chip } from "../ui";

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
 *
 * Each chip routes through the design-library `<Chip/>` (`src/ui/`):
 * `tone={labelColor(...)}` supplies the `.label-chip--<key>` colour, and
 * `className="label-chip"` layers the hand-drawn wobble shape (small
 * font/padding, wobble border-radius, ellipsis clipping) on top of `.qb-chip`
 * — same `.label-chip` class as before this migration, just composed via the
 * primitive instead of a bare `<span>`, so `.label-chip`/`.label-chip--<key>`
 * class-based queries (this file's own tests, `LabelEditor`'s) still match.
 */
function LabelChips({ labels, className, colorRegistry }: LabelChipsProps) {
  // Defensive guard: the contract guarantees `labels` is always present, but
  // treat a missing/undefined value as `[]` rather than crashing.
  const list = labels ?? [];
  if (list.length === 0) return null;

  return (
    <div className={"label-chips" + (className ? ` ${className}` : "")}>
      {list.map((label) => (
        <Chip
          key={label}
          tone={labelColor(label, colorRegistry)}
          className="label-chip"
        >
          {label}
        </Chip>
      ))}
    </div>
  );
}

export default LabelChips;
