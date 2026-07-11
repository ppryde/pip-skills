import type { BoardCard } from "../api/types";
import BudgetMeter from "./BudgetMeter";
import DependencyBadge from "./DependencyBadge";

export interface CardTileProps {
  card: BoardCard;
  dimmed?: boolean;
  highlighted?: boolean;
}

/**
 * Read-only tile. The `.card-tile__handle` element is a placeholder for the
 * drag handle Chunk 4 wires up (@dnd-kit) — no handlers here. Tile body
 * click-to-open-drawer is Chunk 5's concern.
 */
function CardTile({ card, dimmed = false, highlighted = false }: CardTileProps) {
  const className = [
    "card-tile",
    card.status === "blocked" ? "card-tile--blocked" : "",
    dimmed ? "card-tile--dimmed" : "",
    highlighted ? "card-tile--highlighted" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={className} data-card-id={card.id}>
      <div
        className="card-tile__handle"
        aria-hidden="true"
        title="Drag handle (wired in a later chunk)"
      >
        ⠿
      </div>
      <div className="card-tile__body">
        <div className="card-tile__header">
          <span className="card-tile__id">{card.id}</span>
          {card.priority && (
            <span className={`priority-chip priority-chip--${card.priority}`}>
              {card.priority}
            </span>
          )}
          {card.status === "blocked" && (
            <span className="badge badge--blocked">BLOCKED</span>
          )}
        </div>
        <div className="card-tile__title">{card.title}</div>
        <div className="card-tile__footer">
          <BudgetMeter budget={card.budget} />
          <DependencyBadge card={card} />
        </div>
      </div>
    </div>
  );
}

export default CardTile;
