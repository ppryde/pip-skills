import type { BoardCard } from "../api/types";
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
  /** Task 6: true while this card's `cardIconKey` changed within the last
   * 60s (App.tsx's `useIconKeyGlow`, threaded via Lane) — passed straight
   * through to `TileShell`'s `is-glowing` treatment. */
  glowing?: boolean;
  dragDisabled?: boolean;
  /** Chunk 5: clicking the tile body opens the detail drawer for this card. */
  onOpen?: (id: string) => void;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * threaded through to `TileShell`'s `LabelChips`. */
  colorRegistry?: Record<string, string>;
}

/**
 * Pure composition of the shared `TileShell` chrome (drag handle, header,
 * footer). No epic-specific extras.
 */
function CardTile({
  card,
  accentKey,
  dimmed = false,
  highlighted = false,
  branchDimmed = false,
  branchSpotlight = false,
  glowing = false,
  dragDisabled = false,
  onOpen,
  colorRegistry,
}: CardTileProps) {
  return (
    <TileShell
      card={card}
      accentKey={accentKey}
      dimmed={dimmed}
      highlighted={highlighted}
      branchDimmed={branchDimmed}
      branchSpotlight={branchSpotlight}
      glowing={glowing}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
      colorRegistry={colorRegistry}
    />
  );
}

export default CardTile;
