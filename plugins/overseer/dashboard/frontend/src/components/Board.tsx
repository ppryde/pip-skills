import { useCallback, useMemo, useState } from "react";
import {
  DndContext,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import type { Board as BoardModel } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import { groupIntoLanes } from "../board/layout";
import { DRAG_SENSOR_DESCRIPTORS } from "../board/dragSensors";
import { locateDropTarget, resolveDrop } from "../board/dragPlan";
import { runDropPlan } from "../board/runDropPlan";
import Lane from "./Lane";

export interface BoardProps {
  board: BoardModel;
  showArchive: boolean;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Chunk 5: clicking a tile body opens the detail drawer for that card. */
  onOpenCard: (id: string) => void;
}

/**
 * Horizontally-scrollable lane container. Renders exactly the lanes
 * `groupIntoLanes` produces — Parked/Done/Archive sit at the right of the
 * row (see styles.css), and the Archive lane is only rendered when the
 * TopBar toggle (`showArchive`) is on. Empty stage lanes still render (as a
 * thin strip via `.lane--empty` in styles.css) so the board's shape is
 * stable.
 *
 * Owns the ONE `DndContext` for the board. `onDragEnd` derives a `DropPlan`
 * from the pure `resolveDrop` (see board/dragPlan.ts) and hands it to
 * `runDropPlan`, which is the only thing allowed to call `mutate` — this
 * component never calls the api client or `setBoard` directly (see
 * wf005-context.md "Single mutation entrypoint").
 */
function Board({ board, showArchive, mutate, inFlight, onOpenCard }: BoardProps) {
  const lanes = useMemo(() => groupIntoLanes(board.cards), [board.cards]);
  const [highlightedEpicId, setHighlightedEpicId] = useState<string | null>(
    null
  );
  const [dragToast, setDragToast] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(DRAG_SENSOR_DESCRIPTORS[0].sensor, DRAG_SENSOR_DESCRIPTORS[0].options),
    useSensor(DRAG_SENSOR_DESCRIPTORS[1].sensor, DRAG_SENSOR_DESCRIPTORS[1].options)
  );

  const toggleEpicHighlight = (id: string) => {
    setHighlightedEpicId((current) => (current === id ? null : id));
  };

  const visibleLanes = lanes.filter(
    (lane) => lane.kind !== "archive" || showArchive
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over) return;

      const draggedId = String(active.id);
      const dragged = board.cards.find((c) => c.id === draggedId);
      if (!dragged) return;

      const { lane: targetLane, index } = locateDropTarget(
        String(over.id),
        lanes
      );
      if (!targetLane) return;

      const plan = resolveDrop(dragged, targetLane, index, lanes);
      if (plan.calls.length === 0) return;

      const intendedLaneKey = targetLane.key;
      void runDropPlan(plan, mutate).then((response) => {
        // Reconcile: compare the dragged card's RESULTING lane in the
        // response `mutate` just applied against the lane it was dropped
        // on. A mismatch (the server did something other than what the
        // drop implied — e.g. a business rule this UI doesn't know about)
        // surfaces as a toast; the board itself has already re-rendered
        // from the real response, so the tile visually "snaps back" to its
        // actual lane with no extra work here.
        if (!response) return; // no-op plan, or mutate() caught an error (surfaced via useBoard().error already)

        const resultLanes = groupIntoLanes(response.board.cards);
        const resultCard = response.board.cards.find(
          (c) => c.id === dragged.id
        );
        const resultLane = resultLanes.find((l) =>
          l.cards.some((c) => c.id === dragged.id)
        );
        if (resultLane && resultLane.key !== intendedLaneKey) {
          setDragToast(
            `couldn't move ${dragged.id} — resulting status: ${resultCard?.status ?? "unknown"}`
          );
        }
      });
    },
    [board.cards, lanes, mutate]
  );

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="board">
        {dragToast && (
          <div className="board-toast" role="status">
            {dragToast}
            <button
              type="button"
              className="board-toast__dismiss"
              onClick={() => setDragToast(null)}
            >
              dismiss
            </button>
          </div>
        )}
        {visibleLanes.map((lane) => (
          <Lane
            key={lane.key}
            lane={lane}
            highlightedEpicId={highlightedEpicId}
            onToggleEpicHighlight={toggleEpicHighlight}
            dragDisabled={inFlight}
            onOpenCard={onOpenCard}
          />
        ))}
      </div>
    </DndContext>
  );
}

export default Board;
