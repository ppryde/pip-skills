import { useMemo, useState } from "react";
import type { Board as BoardModel } from "../api/types";
import { groupIntoLanes } from "../board/layout";
import Lane from "./Lane";

export interface BoardProps {
  board: BoardModel;
  showArchive: boolean;
}

/**
 * Horizontally-scrollable lane container. Renders exactly the lanes
 * `groupIntoLanes` produces — Parked/Done/Archive sit at the right of the
 * row (see styles.css), and the Archive lane is only rendered when the
 * TopBar toggle (`showArchive`) is on. Empty stage lanes still render (as a
 * thin strip via `.lane--empty` in styles.css) so the board's shape is
 * stable.
 */
function Board({ board, showArchive }: BoardProps) {
  const lanes = useMemo(() => groupIntoLanes(board.cards), [board.cards]);
  const [highlightedEpicId, setHighlightedEpicId] = useState<string | null>(
    null
  );

  const toggleEpicHighlight = (id: string) => {
    setHighlightedEpicId((current) => (current === id ? null : id));
  };

  const visibleLanes = lanes.filter(
    (lane) => lane.kind !== "archive" || showArchive
  );

  return (
    <div className="board">
      {visibleLanes.map((lane) => (
        <Lane
          key={lane.key}
          lane={lane}
          highlightedEpicId={highlightedEpicId}
          onToggleEpicHighlight={toggleEpicHighlight}
        />
      ))}
    </div>
  );
}

export default Board;
