import type { BoardCard } from "../api/types";
import { formatTokens } from "../board/formatTokens";
import TileShell from "./TileShell";

export interface EpicCardProps {
  card: BoardCard;
  /** Lane-computed guild accent key (WF-028) — e.g. "backlog",
   * "plan-review", "parked" — threaded through to `TileShell`'s chrome. */
  accentKey?: string;
  expanded: boolean;
  onToggleExpand: (id: string) => void;
  dimmed?: boolean;
  highlighted?: boolean;
  /** WF-031 branch filter — see TileShell's doc comment. */
  branchDimmed?: boolean;
  branchSpotlight?: boolean;
  dragDisabled?: boolean;
  /** Chunk 5: clicking the tile body opens the detail drawer for this card. */
  onOpen?: (id: string) => void;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * threaded through to `TileShell`'s `LabelChips`. */
  colorRegistry?: Record<string, string>;
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
  accentKey,
  expanded,
  onToggleExpand,
  dimmed = false,
  highlighted = false,
  branchDimmed = false,
  branchSpotlight = false,
  dragDisabled = false,
  onOpen,
  colorRegistry,
}: EpicCardProps) {
  const rollup = card.rollup;

  return (
    <TileShell
      card={card}
      accentKey={accentKey}
      variantClassName="epic-card"
      dimmed={dimmed}
      highlighted={highlighted}
      branchDimmed={branchDimmed}
      branchSpotlight={branchSpotlight}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
      colorRegistry={colorRegistry}
      headerExtra={
        // WF-097 follow-up: deliberately left as a bare `<button>`, NOT
        // `<Button>` — `.epic-card__expand` is a small legacy indigo toggle
        // chip, deliberately its OWN paint (the atlas rail's Role-A expand
        // button even calls this out as the look it does NOT reuse), so
        // routing it through the `.qb-btn` primitive would repaint it with
        // the wrong chrome entirely.
        <button
          type="button"
          className="epic-card__expand"
          onClick={(e) => {
            // Stop the click from bubbling to the body's onOpen — expanding
            // the epic's highlight is a distinct action from opening the
            // detail drawer, even though the button lives inside the body.
            e.stopPropagation();
            onToggleExpand(card.id);
          }}
          aria-expanded={expanded}
        >
          {expanded ? "collapse" : "expand"}
        </button>
      }
    >
      {rollup && (
        <div
          className="epic-card__rollup"
          title={`${rollup.actual} vs ${rollup.estimate ?? "—"} est.`}
        >
          {rollup.done}/{rollup.total} done · {formatTokens(rollup.actual)} vs{" "}
          {rollup.estimate !== null ? formatTokens(rollup.estimate) : "—"} est.
        </div>
      )}
    </TileShell>
  );
}

export default EpicCard;
