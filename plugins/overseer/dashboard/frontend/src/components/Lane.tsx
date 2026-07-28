import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import type { Lane as LaneModel } from "../board/layout";
import CardTile from "./CardTile";
import EpicCard from "./EpicCard";

export interface LaneProps {
  lane: LaneModel;
  highlightedEpicId: string | null;
  onToggleEpicHighlight: (id: string) => void;
  /** True while a mutation is in flight — passed through to disable drag handles. */
  dragDisabled: boolean;
  /** Chunk 5: clicking a tile body opens the detail drawer for that card. */
  onOpenCard: (id: string) => void;
}

/**
 * A single column: header (label + count) + a vertical list of tiles.
 * Placement of cards into this lane is entirely `layout.ts`'s job — this
 * component just renders whatever `lane.cards` it is given, in order.
 *
 * The OUTER element is the lane's droppable target (`useDroppable({id:
 * lane.key})`) so an empty lane (which renders no `.lane__cards` list) is
 * still a valid drop target — `Board.tsx`'s `locateDropTarget` falls back to
 * "append at the end of this lane" when `over.id` is the lane key itself
 * rather than a card id.
 */
function Lane({
  lane,
  highlightedEpicId,
  onToggleEpicHighlight,
  dragDisabled,
  onOpenCard,
}: LaneProps) {
  const { setNodeRef } = useDroppable({ id: lane.key });
  const isEmpty = lane.cards.length === 0;
  const className = [
    "lane",
    `lane--${lane.kind}`,
    isEmpty ? "lane--empty" : "",
  ]
    .filter(Boolean)
    .join(" ");

  // Guild banner/card accent key (WF-028): mirrors HANDOFF's per-column
  // accent table. Archive maps explicitly onto "parked" — there are 11
  // lanes but only 10 `--qb-col-*` tokens (Archive reuses the taupe/Parked
  // accent group, an adjudicated off-board/shelved semantic — no HANDOFF
  // row exists for Archive). A literal "archive" key would resolve a
  // phantom token and silently drop the banner fill.
  const accentKey =
    lane.kind === "archive"
      ? "parked"
      : lane.kind === "stage"
        ? lane.stage!
        : lane.kind;

  return (
    <div className={className} data-lane-key={lane.key} ref={setNodeRef}>
      <div className={`lane__header lane__header--${accentKey}`}>
        <span className="lane__label">{lane.label}</span>
        <span className="lane__count">{lane.cards.length}</span>
      </div>
      <SortableContext
        items={lane.cards.map((c) => c.id)}
        strategy={verticalListSortingStrategy}
      >
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
                  accentKey={accentKey}
                  expanded={highlightedEpicId === card.id}
                  onToggleExpand={onToggleEpicHighlight}
                  dimmed={dimmed}
                  highlighted={highlighted}
                  dragDisabled={dragDisabled}
                  onOpen={onOpenCard}
                />
              ) : (
                <CardTile
                  key={card.id}
                  card={card}
                  accentKey={accentKey}
                  dimmed={dimmed}
                  highlighted={highlighted}
                  dragDisabled={dragDisabled}
                  onOpen={onOpenCard}
                />
              );
            })}
          </div>
        )}
      </SortableContext>
    </div>
  );
}

export default Lane;
