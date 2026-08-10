import type { BoardCard } from "../api/types";
import { STAGE_LABELS } from "../board/layout";
import { stageIcon } from "../board/laneIcons";
import TileShell from "./TileShell";

export interface CardTileProps {
  card: BoardCard;
  /** Lane-computed guild accent key (WF-028) — e.g. "backlog",
   * "plan-review", "parked" — threaded through to `TileShell`'s chrome. */
  accentKey?: string;
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
  /** WF-085 in-progress lane, Part B: true only for cards rendered in the
   * MOBILE merged "In Progress" lane (`Lane.tsx` gates this off the lane's
   * own `kind === "in-progress"` — that kind never exists on desktop, so
   * this is mobile-only by construction). Renders a small stage icon (the
   * SAME PNG the card's own `stage:<S>` lane would use on desktop, via
   * `stageIcon`) next to the id, with an accessible label — the stage each
   * card is at, now that it no longer has its own lane to show that. A
   * card with no `stage` (shouldn't happen inside this lane, but defensive)
   * renders nothing extra. */
  showStage?: boolean;
}

/**
 * Pure composition of the shared `TileShell` chrome (drag handle, header,
 * footer). No epic-specific extras beyond the optional mobile stage icon.
 */
function CardTile({
  card,
  accentKey,
  dimmed = false,
  highlighted = false,
  branchDimmed = false,
  branchSpotlight = false,
  dragDisabled = false,
  onOpen,
  colorRegistry,
  showStage = false,
}: CardTileProps) {
  return (
    <TileShell
      card={card}
      accentKey={accentKey}
      dimmed={dimmed}
      highlighted={highlighted}
      branchDimmed={branchDimmed}
      branchSpotlight={branchSpotlight}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
      colorRegistry={colorRegistry}
      headerExtra={
        showStage && card.stage ? (
          <img
            className="card-tile__stage-icon"
            src={stageIcon(card.stage)}
            alt={STAGE_LABELS[card.stage]}
          />
        ) : undefined
      }
    />
  );
}

export default CardTile;
