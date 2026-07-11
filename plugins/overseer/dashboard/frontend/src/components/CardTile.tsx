import type { BoardCard } from "../api/types";
import TileShell from "./TileShell";

export interface CardTileProps {
  card: BoardCard;
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
  dimmed = false,
  highlighted = false,
  dragDisabled = false,
  onOpen,
}: CardTileProps) {
  return (
    <TileShell
      card={card}
      dimmed={dimmed}
      highlighted={highlighted}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
    />
  );
}

export default CardTile;
