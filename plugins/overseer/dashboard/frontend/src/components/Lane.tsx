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
  /** WF-031 branch filter: `null` clears it (no dim/spotlight anywhere);
   * otherwise every card that HAS a `branch` differing from it gets dimmed
   * and every matching card gets spotlit — independent of the epic-highlight
   * state above. A card with NO branch (never started) stays neutral: it's
   * not "on another branch", it just hasn't got one yet (task 10). */
  activeBranch: string | null;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * threaded through to every CardTile/EpicCard's LabelChips. */
  colorRegistry?: Record<string, string>;
}

/**
 * A single column: header (label) + a vertical list of tiles.
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
  activeBranch,
  colorRegistry,
}: LaneProps) {
  const { setNodeRef } = useDroppable({ id: lane.key });
  const isEmpty = lane.cards.length === 0;

  // Guild banner/card accent key (WF-028): mirrors HANDOFF's per-column
  // accent table. Archive (labelled "Abandoned") gets its own muted
  // "abandoned"/ash accent group (WF-076) — it used to borrow "parked"'s
  // taupe, which made abandoned and parked cards visually identical.
  // Computed before `className` so the lane root can carry it too — the light
  // lane fill (WF-092) tints off the same accent as the header banner.
  const accentKey =
    lane.kind === "archive"
      ? "abandoned"
      : lane.kind === "stage"
        ? lane.stage!
        : lane.kind;

  const className = [
    "lane",
    `lane--${lane.kind}`,
    `lane--accent-${accentKey}`,
    isEmpty ? "lane--empty" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={className} data-lane-key={lane.key} ref={setNodeRef}>
      {/* WF-085: the card count no longer duplicates here — it lives only
          in the mobile icon-nav strip (LaneIconNav), which reads
          `lane.cards.length` itself. Desktop had no other consumer of
          `.lane__count`, so this is a straight removal, not a move of
          markup. */}
      <div className={`lane__header lane__header--${accentKey}`}>
        <span className="lane__label">{lane.label}</span>
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

              // Task 10: a card with NO branch (todo/backlog, never started)
              // is neither "this branch" nor "some other branch" — it stays
              // neutral under a branch filter rather than dimming alongside
              // cards that actively belong to a DIFFERENT branch. Only a
              // card that HAS a branch that differs from the active one
              // gets dimmed.
              const branchDimmed =
                activeBranch !== null &&
                card.branch != null &&
                card.branch !== activeBranch;
              const branchSpotlight =
                activeBranch !== null && card.branch === activeBranch;

              return card.is_epic ? (
                <EpicCard
                  key={card.id}
                  card={card}
                  accentKey={accentKey}
                  expanded={highlightedEpicId === card.id}
                  onToggleExpand={onToggleEpicHighlight}
                  dimmed={dimmed}
                  highlighted={highlighted}
                  branchDimmed={branchDimmed}
                  branchSpotlight={branchSpotlight}
                  dragDisabled={dragDisabled}
                  onOpen={onOpenCard}
                  colorRegistry={colorRegistry}
                />
              ) : (
                <CardTile
                  key={card.id}
                  card={card}
                  accentKey={accentKey}
                  dimmed={dimmed}
                  highlighted={highlighted}
                  branchDimmed={branchDimmed}
                  branchSpotlight={branchSpotlight}
                  dragDisabled={dragDisabled}
                  onOpen={onOpenCard}
                  colorRegistry={colorRegistry}
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
