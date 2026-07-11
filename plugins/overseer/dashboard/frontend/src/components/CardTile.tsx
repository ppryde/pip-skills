import type { BoardCard } from "../api/types";
import TileShell from "./TileShell";

export interface CardTileProps {
  card: BoardCard;
  dimmed?: boolean;
  highlighted?: boolean;
  dragDisabled?: boolean;
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
}: CardTileProps) {
  return (
    <TileShell
      card={card}
      dimmed={dimmed}
      highlighted={highlighted}
      dragDisabled={dragDisabled}
    />
  );
}

export default CardTile;
