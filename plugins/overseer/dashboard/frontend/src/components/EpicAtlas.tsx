import { useCallback, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { Board, BoardCard } from "../api/types";
import { accentKeyForCard } from "../board/cardAccent";
import { parseCalendarDate } from "../board/atlasGeometry";
import {
  BEAST_RESERVE_PX,
  globalPxPerWeight,
  laneUsableWidth,
  openDependencies,
  orderEpicsForDisplay,
  totalWeight,
  trailEndX,
} from "../board/atlasTrailLayout";
import { useMediaQuery } from "../board/useMediaQuery";
import AtlasRailCard from "./AtlasRailCard";
import AtlasTrail from "./AtlasTrail";

export interface EpicAtlasProps {
  board: Board;
  /** Chunk 5 precedent (Board/EpicCard): clicking a rail card body opens
   * the existing detail drawer for that card — App's drawer, unchanged. */
  onOpenCard: (id: string) => void;
  /** WF-091: the toolbar toggles are now App-owned, lifted state
   * (was local to this component, driven by the since-retired
   * `<AtlasToolbar>`) — the controls themselves now live in TopBar's
   * Controls group. Show quest name-tags on the trail; default true. */
  showNames: boolean;
  /** Hide vanquished (done) epics; default true. */
  hideVanquished: boolean;
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
 *
 * WF-091: `showNames`/`hideVanquished` are now PROPS —
 * App.tsx owns them as lifted state, and the controls that drive them moved
 * into TopBar's Controls group (the standalone `<AtlasToolbar>` that used
 * to render here, between the topbar and the chart, is retired).
 */
function EpicAtlas({ board, onOpenCard, showNames, hideVanquished }: EpicAtlasProps) {
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(new Set());
  const isMobile = useMediaQuery("(max-width:720px)");
  // Mobile across-view POC: on mobile (never desktop) a trail-child tap pops
  // a small preview card up above that node — rendered inside AtlasTrail's
  // own overlay layer so it sits at the tapped marker's x and scrolls with
  // the trail — instead of opening the full drawer. One preview at a time;
  // tapping the already-open child toggles it back off, and tapping a
  // different child just moves the popup. Desktop keeps the real drawer flow
  // (`onOpenCard`) untouched.
  const [previewChildId, setPreviewChildId] = useState<string | null>(null);

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

  // Feature 1 (WF-086 v3, wide-view overspill): the SVG content width EVERY
  // Across-mode lane renders at — deliberately NOT `laneWidth`. Once
  // `MIN_PX_PER_WEIGHT` floors `pxPerWeight` above (a cramped board), the
  // heaviest visible epic's true end can exceed the lane's own
  // viewport-constrained width; `trailWidth` is that heaviest epic's own
  // trailEnd + beast reserve, shared by EVERY row so they all stay
  // column-aligned (the same "one shared scale" discipline as `pxPerWeight`
  // itself). `AtlasTrail.tsx` renders its SVG at this width and lets it
  // OVERFLOW the (still laneWidth-sized) lane rather than the lane growing
  // to match — see that component's doc comment for why the lane must
  // never be resized here (a resize would re-feed `laneWidth`'s own
  // ResizeObserver and runaway).
  const trailWidth = useMemo(() => {
    const maxTotalWeight = Math.max(
      1,
      ...epics.map((epic) => totalWeight(childrenByEpic.get(epic.id) ?? []))
    );
    return trailEndX(maxTotalWeight, pxPerWeight) + BEAST_RESERVE_PX;
  }, [epics, childrenByEpic, pxPerWeight]);

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
      <div
        className="atlas-chart"
        // Shared trail width, exposed so the mobile row-divider pseudo-element
        // (styles.css) can span the full lane the SVG overflows into.
        style={{ ["--trail-w" as string]: `${trailWidth}px` } as CSSProperties}
      >
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
                      cardsById={cardsById}
                    />
                  </div>
                  <div className="atlas-chart__lane" ref={i === 0 ? firstLaneRef : undefined}>
                    <AtlasTrail
                      card={epic}
                      rollup={rollup}
                      childCards={childCards}
                      cardsById={cardsById}
                      pxPerWeight={pxPerWeight}
                      trailWidth={trailWidth}
                      showNames={showNames}
                      onOpenCard={
                        isMobile
                          ? (id) =>
                              setPreviewChildId((prev) =>
                                prev === id ? null : id
                              )
                          : onOpenCard
                      }
                      previewChildId={isMobile ? previewChildId : null}
                      onOpenDrawer={onOpenCard}
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
