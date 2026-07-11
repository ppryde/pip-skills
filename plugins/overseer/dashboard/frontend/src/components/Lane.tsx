import type { Lane as LaneModel } from "../board/layout";
import CardTile from "./CardTile";
import EpicCard from "./EpicCard";

export interface LaneProps {
  lane: LaneModel;
  highlightedEpicId: string | null;
  onToggleEpicHighlight: (id: string) => void;
}

/**
 * A single column: header (label + count) + a vertical list of tiles.
 * Placement of cards into this lane is entirely `layout.ts`'s job — this
 * component just renders whatever `lane.cards` it is given, in order.
 */
function Lane({ lane, highlightedEpicId, onToggleEpicHighlight }: LaneProps) {
  const isEmpty = lane.cards.length === 0;
  const className = [
    "lane",
    `lane--${lane.kind}`,
    isEmpty ? "lane--empty" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={className} data-lane-key={lane.key}>
      <div className="lane__header">
        <span className="lane__label">{lane.label}</span>
        <span className="lane__count">{lane.cards.length}</span>
      </div>
      {!isEmpty && (
        <div className="lane__cards">
          {lane.cards.map((card) => {
            const isChildOfHighlighted =
              highlightedEpicId !== null && card.parent === highlightedEpicId;
            const isHighlightedEpic =
              highlightedEpicId !== null && card.id === highlightedEpicId;
            const highlighted = isChildOfHighlighted || isHighlightedEpic;
            const dimmed = highlightedEpicId !== null && !highlighted;

            return card.is_epic ? (
              <EpicCard
                key={card.id}
                card={card}
                expanded={highlightedEpicId === card.id}
                onToggleExpand={onToggleEpicHighlight}
                dimmed={dimmed}
                highlighted={highlighted}
              />
            ) : (
              <CardTile
                key={card.id}
                card={card}
                dimmed={dimmed}
                highlighted={highlighted}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export default Lane;
