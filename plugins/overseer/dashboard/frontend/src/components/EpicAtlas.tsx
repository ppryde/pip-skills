import { useCallback, useMemo, useRef, useState } from "react";
import type { Board, BoardCard } from "../api/types";
import { accentKeyForCard } from "../board/cardAccent";
import { parseCalendarDate } from "../board/atlasGeometry";
import {
  globalPxPerWeight,
  laneUsableWidth,
  openDependencies,
  orderEpicsForDisplay,
  totalWeight,
} from "../board/atlasTrailLayout";
import AtlasRailCard from "./AtlasRailCard";
import AtlasToolbar, { type TrailOrientation } from "./AtlasToolbar";
import AtlasTrail from "./AtlasTrail";

export interface EpicAtlasProps {
  board: Board;
  /** Chunk 5 precedent (Board/EpicCard): clicking a rail card body opens
   * the existing detail drawer for that card — App's drawer, unchanged. */
  onOpenCard: (id: string) => void;
}

const EMPTY_STATE_COPY = "No sagas yet — give a quest children and it becomes a campaign.";

/** Used for the shared px-per-weight scale until the first real
 * ResizeObserver measurement of a lane lands — mirrors AtlasTrail's own
 * DEFAULT_LANE_HEIGHT fallback-before-measurement convention. */
const DEFAULT_LANE_WIDTH = 600;

/**
 * Epic Atlas page (WF-086 v2, progress-trail revision) — a gantt-esque
 * sibling view to the board, one progress-trail row per epic. Filters
 * `board.cards` to `is_epic` cards that ALSO carry a non-null `rollup` (an
 * epic minted without one yet has no done/total to plot); every other
 * epic/child grouping is a plain `cards.filter(c => c.parent === epic.id)`,
 * no new endpoints.
 *
 * v1's date-axis machinery (TODAY signpost, weekly ticks, pace-projection
 * footnote, mount-scroll-to-today) is KILLED here — see HANDOFF's "Killed
 * from v1". Trail position is now driven by cumulative child complexity on
 * ONE shared `pxPerWeight` scale, computed once per render across every
 * VISIBLE epic (see `atlasTrailLayout.ts`) — `laneWidth` is measured off a
 * single representative lane (all lanes share the same CSS width; only
 * each lane's own HEIGHT is sampled independently, since an expanded
 * checklist can grow one row without affecting its neighbours).
 *
 * `.atlas-chart` is the page's ONE horizontal scroller (the `725ddea`
 * mobile invariant) — no extra scroll wrapper around it.
 */
function EpicAtlas({ board, onOpenCard }: EpicAtlasProps) {
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(new Set());
  const [showNames, setShowNames] = useState(true);
  const [hideVanquished, setHideVanquished] = useState(true);
  const [orientation, setOrientation] = useState<TrailOrientation>("across");

  const [laneWidth, setLaneWidth] = useState(DEFAULT_LANE_WIDTH);
  const laneWidthObserver = useRef<ResizeObserver | null>(null);
  // A callback ref (not a plain useRef + effect) so the observer re-attaches
  // whenever REACT swaps which DOM node is "the first lane" (e.g. the
  // vanquished toggle removes row 0 and a different epic's lane becomes
  // first) — a plain mount-only effect would keep observing a detached node.
  const firstLaneRef = useCallback((el: HTMLDivElement | null) => {
    laneWidthObserver.current?.disconnect();
    laneWidthObserver.current = null;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const measured = entry.contentRect.width;
      setLaneWidth(Number.isFinite(measured) && measured > 0 ? measured : DEFAULT_LANE_WIDTH);
    });
    observer.observe(el);
    laneWidthObserver.current = observer;
  }, []);

  const cardsById = useMemo(() => {
    const map = new Map<string, BoardCard>();
    for (const c of board.cards) map.set(c.id, c);
    return map;
  }, [board.cards]);

  const allEpics = useMemo(
    () =>
      board.cards
        .filter((c) => c.is_epic && c.rollup !== null)
        .sort((a, b) => parseCalendarDate(a.created).getTime() - parseCalendarDate(b.created).getTime()),
    [board.cards]
  );

  const childrenByEpic = useMemo(() => {
    const map = new Map<string, BoardCard[]>();
    for (const epic of allEpics) {
      map.set(epic.id, board.cards.filter((c) => c.parent === epic.id));
    }
    return map;
  }, [allEpics, board.cards]);

  // Vanquished toggle applies AFTER the created-ascending base order (HANDOFF:
  // hidden filters done epics out; shown, they sort last, everything else
  // keeping its relative order) — seedFor is id-keyed, not index-keyed, so
  // toggling this can never re-wobble a surviving trail (atlasTrailLayout.ts).
  const epics = useMemo(
    () => orderEpicsForDisplay(allEpics, hideVanquished),
    [allEpics, hideVanquished]
  );

  // ONE shared px-per-weight scale, recomputed each render across every
  // VISIBLE epic (HANDOFF) — a vanquished epic hidden by the toggle above
  // must never stretch/compress the scale for the epics actually on screen.
  const pxPerWeight = useMemo(() => {
    const totalWeights = epics.map((epic) => totalWeight(childrenByEpic.get(epic.id) ?? []));
    const usable = laneUsableWidth(laneWidth);
    return globalPxPerWeight(totalWeights, usable);
  }, [epics, childrenByEpic, laneWidth]);

  function toggleExpand(id: string) {
    setExpandedEpics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function blockedOnFor(epic: BoardCard): string[] {
    return openDependencies(epic, cardsById);
  }

  return (
    <div className="atlas-page">
      {epics.length > 0 && (
        <AtlasToolbar
          showNames={showNames}
          onToggleNames={setShowNames}
          hideVanquished={hideVanquished}
          onToggleVanquished={setHideVanquished}
          orientation={orientation}
          onToggleOrientation={setOrientation}
        />
      )}
      <div className={"atlas-chart" + (orientation === "down" ? " atlas-chart--down" : "")}>
        {epics.length === 0 ? (
          <p className="atlas-chart__empty">{EMPTY_STATE_COPY}</p>
        ) : (
          <div className="atlas-chart__rows">
            {epics.map((epic, i) => {
              const childCards = childrenByEpic.get(epic.id) ?? [];
              const accentKey = accentKeyForCard(epic);
              const rollup = epic.rollup!;
              return (
                <div key={epic.id} className="atlas-chart__row">
                  <div className="atlas-chart__rail">
                    <AtlasRailCard
                      card={epic}
                      rollup={rollup}
                      childCards={childCards}
                      expanded={expandedEpics.has(epic.id)}
                      onToggleExpand={toggleExpand}
                      onOpen={onOpenCard}
                      accentKey={accentKey}
                      blockedOn={blockedOnFor(epic)}
                    />
                  </div>
                  <div className="atlas-chart__lane" ref={i === 0 ? firstLaneRef : undefined}>
                    <AtlasTrail
                      card={epic}
                      rollup={rollup}
                      childCards={childCards}
                      cardsById={cardsById}
                      pxPerWeight={pxPerWeight}
                      laneWidth={laneWidth}
                      showNames={showNames}
                      accentKey={accentKey}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default EpicAtlas;
