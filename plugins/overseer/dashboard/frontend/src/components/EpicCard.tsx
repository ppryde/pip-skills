import type { BoardCard } from "../api/types";
import TileShell from "./TileShell";

export interface EpicCardProps {
  card: BoardCard;
  expanded: boolean;
  onToggleExpand: (id: string) => void;
  dimmed?: boolean;
  highlighted?: boolean;
}

/**
 * Renders exactly where `layout.ts` placed the epic by its OWN status/stage
 * — same as any card. Composes the shared `TileShell` and only ADDS a rollup
 * line and an expand affordance; it never nests, hides, or duplicates the
 * epic's children. The "highlight children in place" behaviour lives in the
 * parent (Board), which dims non-children across all lanes — this component
 * just renders the toggle and its own highlighted/dimmed state.
 */
function EpicCard({
  card,
  expanded,
  onToggleExpand,
  dimmed = false,
  highlighted = false,
}: EpicCardProps) {
  const rollup = card.rollup;

  return (
    <TileShell
      card={card}
      variantClassName="epic-card"
      dimmed={dimmed}
      highlighted={highlighted}
      headerExtra={
        <button
          type="button"
          className="epic-card__expand"
          onClick={() => onToggleExpand(card.id)}
          aria-expanded={expanded}
        >
          {expanded ? "collapse" : "expand"}
        </button>
      }
    >
      {rollup && (
        <div className="epic-card__rollup">
          {rollup.done}/{rollup.total} done · {rollup.actual} vs{" "}
          {rollup.estimate ?? "—"} est.
        </div>
      )}
    </TileShell>
  );
}

export default EpicCard;
