import type { BoardCard } from "../api/types";
import TileShell from "./TileShell";

export interface CardTileProps {
  card: BoardCard;
  /** Lane-computed guild accent key (WF-028) — e.g. "backlog",
   * "plan-review", "parked" — threaded through to `TileShell`'s chrome. */
  accentKey?: string;
  dimmed?: boolean;
  highlighted?: boolean;
  dragDisabled?: boolean;
  /** Chunk 5: clicking the tile body opens the detail drawer for this card. */
  onOpen?: (id: string) => void;
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
  dragDisabled = false,
  onOpen,
}: CardTileProps) {
  return (
    <TileShell
      card={card}
      accentKey={accentKey}
      dimmed={dimmed}
      highlighted={highlighted}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
    />
  );
}

export default CardTile;
