import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Board, BoardCard } from "../api/types";
import { accentKeyForCard, bannerLabelForCard } from "../board/cardAccent";
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
import { rarityStars } from "../board/rarityStars";
import { useMediaQuery } from "../board/useMediaQuery";
import AtlasRailCard from "./AtlasRailCard";
import AtlasTrail from "./AtlasTrail";
import AtlasTrailVertical from "./AtlasTrailVertical";
import { StarIcon } from "./icons";
import type { TrailOrientation } from "./TopBar";

export interface EpicAtlasProps {
  board: Board;
  /** Chunk 5 precedent (Board/EpicCard): clicking a rail card body opens
   * the existing detail drawer for that card — App's drawer, unchanged. */
  onOpenCard: (id: string) => void;
  /** WF-091: the three toolbar toggles are now App-owned, lifted state
   * (was local to this component, driven by the since-retired
   * `<AtlasToolbar>`) — the controls themselves now live in TopBar's
   * Controls group. Show quest name-tags on the trail; default true. */
  showNames: boolean;
  /** Hide vanquished (done) epics; default true. */
  hideVanquished: boolean;
  /** Mobile trail orientation — see `downMode` below for the <=720px-only
   * effective gate (desktop always renders across regardless of this). */
  orientation: TrailOrientation;
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
 * mobile invariant) — no extra scroll wrapper around it. The mobile
 * Down-mode column layout is a SEPARATE scroll axis (HANDOFF: "the two
 * axes never fight") — see the `downMode` branch below, gated on BOTH the
 * `orientation` prop AND the real ≤720px viewport (the prop is inert on
 * desktop, which always renders across).
 *
 * WF-091: `showNames`/`hideVanquished`/`orientation` are now PROPS —
 * App.tsx owns them as lifted state, and the controls that drive them moved
 * into TopBar's Controls group (the standalone `<AtlasToolbar>` that used
 * to render here, between the topbar and the chart, is retired).
 */
function EpicAtlas({ board, onOpenCard, showNames, hideVanquished, orientation }: EpicAtlasProps) {
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(new Set());
  const isMobile = useMediaQuery("(max-width:720px)");
  const downMode = isMobile && orientation === "down";
  // Mobile ACROSS POC (WF-atlas-across-poc): mobile-across is "mobile, but
  // NOT down-mode" — the only orientation where the horizontal SVG trail
  // still renders (Down-mode swaps it for vertical columns, see the
  // `downMode` branch below). Desktop (`isMobile` false) is completely
  // unaffected regardless of `orientation` — the prop is inert there
  // (EpicAtlas's own doc comment above). Every mobile-across-only behaviour
  // in this file — the tap-to-preview overlay below, and its mirror in
  // styles.css's `@media (max-width:720px)` layer — is gated on this one
  // flag so desktop and down-mode stay byte-for-byte unchanged.
  const mobileAcross = isMobile && !downMode;

  // Tap-to-preview state (POC): which CHILD card's trail marker/name-tag was
  // last tapped, on mobile-across only — `null` means no preview is open.
  // Deliberately a single id shared across every row (not per-epic state):
  // a child belongs to exactly one epic by construction (`child.parent`),
  // so "only one preview at a time across the whole page" falls out for
  // free — whichever row's epic id matches `previewChild.parent` renders it,
  // every other row's lookup below just no-ops. If the id ever points at a
  // card that no longer exists (e.g. deleted mid-preview), `cardsById.get`
  // returns `undefined` and the row-level guard below treats that exactly
  // like "no preview" — no crash, no stale render.
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

  // Down-mode's own scroller (a distinct element from `.atlas-chart` in
  // across-mode — Down's columns scroll horizontally, so `.atlas-chart`
  // itself is that scroller here too, just with a different child shape).
  const columnsRef = useRef<HTMLDivElement>(null);
  const [activeColumnHeight, setActiveColumnHeight] = useState<number | null>(null);
  // Only the setter is used (retargeting the ResizeObserver below reads a
  // local closure variable, not this state — see that effect's own
  // comment) — kept for a future active-column highlight affordance, not
  // read anywhere yet.
  const [, setActiveColumnIndex] = useState(0);

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
  // Down-mode doesn't use this at all — AtlasTrailVertical has its own flat
  // per-column scale (see that component's doc comment).
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

  // Port of Board.tsx's `activeLaneHeight` technique (HANDOFF explicitly
  // calls this out) — a scroll listener finds whichever column sits
  // nearest the scroller's own centre and pins `.atlas-chart__columns`'
  // own box to THAT column's `scrollHeight` (`overflow-y: hidden` in CSS
  // clips the other, off-screen, possibly-taller columns out of the
  // scrollable region), with a ResizeObserver re-measuring if the active
  // column's own content changes size (e.g. its checklist expands).
  //
  // Impl-review round 1, finding 2: the observer used to attach ONCE, to
  // whichever column `activeColumnIndex` (a stale render-time closure over
  // React state) named when the effect last RAN — swiping to a different
  // column fires the scroll listener (which updates the STATE) but never
  // re-runs this effect, so the observer kept watching the column that was
  // active back when the effect was set up, not whichever one actually is
  // now. Expanding a swiped-to column's checklist (no scroll event at all)
  // then left `.atlas-chart__columns` pinned at a stale height with
  // `overflow-y: hidden` clipping the real content. Fixed by re-pointing
  // the SAME observer instance at the newly-nearest element from directly
  // inside `measure()` (a local closure variable, not React state — no
  // extra render/effect churn needed to keep it current) every time
  // `measure()` runs, whether triggered by scroll OR by the observer
  // itself firing on the currently-watched column's own resize.
  useLayoutEffect(() => {
    if (!downMode) {
      setActiveColumnHeight(null);
      return;
    }
    const scroller = columnsRef.current;
    if (!scroller) return;

    // jsdom (unlike every real browser) has no ResizeObserver in every test
    // environment — same guard as Board.tsx's own port of this technique.
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : undefined;
    let observedEl: HTMLElement | null = null;

    function measure() {
      const rect = scroller!.getBoundingClientRect();
      const centre = rect.left + rect.width / 2;
      let nearestIndex = 0;
      let nearestDistance = Infinity;
      let nearestEl: HTMLElement | null = null;
      scroller!.querySelectorAll<HTMLElement>("[data-column-index]").forEach((el) => {
        const r = el.getBoundingClientRect();
        const d = Math.abs(r.left + r.width / 2 - centre);
        if (d < nearestDistance) {
          nearestDistance = d;
          nearestIndex = Number(el.dataset.columnIndex);
          nearestEl = el;
        }
      });
      setActiveColumnIndex(nearestIndex);
      if (nearestEl) setActiveColumnHeight((nearestEl as HTMLElement).scrollHeight);

      if (ro && nearestEl !== observedEl) {
        if (observedEl) ro.unobserve(observedEl);
        if (nearestEl) ro.observe(nearestEl);
        observedEl = nearestEl;
      }
    }

    measure();
    scroller.addEventListener("scroll", measure);

    return () => {
      scroller.removeEventListener("scroll", measure);
      ro?.disconnect();
    };
  }, [downMode, epics.length]);

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
      <div className={"atlas-chart" + (downMode ? " atlas-chart--down" : "")}>
        {epics.length === 0 ? (
          <p className="atlas-chart__empty">{EMPTY_STATE_COPY}</p>
        ) : downMode ? (
          <div
            className="atlas-chart__columns"
            ref={columnsRef}
            style={activeColumnHeight != null ? { height: `${activeColumnHeight}px` } : undefined}
          >
            {epics.map((epic, i) => {
              const childCards = childrenByEpic.get(epic.id) ?? [];
              const accentKey = accentKeyForCard(epic);
              const rollup = epic.rollup!;
              return (
                <div key={epic.id} className="atlas-chart__column" data-column-index={i}>
                  <div className="atlas-chart__column-card">
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
                  <div className="atlas-chart__column-lane">
                    <AtlasTrailVertical
                      card={epic}
                      rollup={rollup}
                      childCards={childCards}
                      cardsById={cardsById}
                      showNames={showNames}
                      onOpenCard={onOpenCard}
                      accentKey={accentKey}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="atlas-chart__rows">
            {epics.map((epic, i) => {
              const childCards = childrenByEpic.get(epic.id) ?? [];
              const accentKey = accentKeyForCard(epic);
              const rollup = epic.rollup!;

              // Mobile-across POC: a trail click sets the preview overlay
              // instead of opening the real drawer — desktop and down-mode
              // (`mobileAcross` false there) keep calling `onOpenCard`
              // exactly as before, so AtlasTrail's own click behaviour is
              // completely untouched outside this one gate.
              const trailOnOpenCard = mobileAcross
                ? (childId: string) => setPreviewChildId(childId)
                : onOpenCard;

              // The previewed child, scoped to THIS row's epic — a child
              // belongs to exactly one epic, so at most one row's guard
              // below ever passes (the "one preview at a time" contract).
              // `cardsById.get` returning `undefined` for a stale/deleted
              // id is handled by the same falsy check, no separate guard
              // needed.
              const previewChild =
                mobileAcross && previewChildId ? cardsById.get(previewChildId) : undefined;
              const showPreview = previewChild != null && previewChild.parent === epic.id;
              const previewStars = previewChild ? rarityStars(previewChild.complexity) : 0;
              const previewDone = previewChild
                ? previewChild.checklist.filter((entry) => entry.status === "completed").length
                : 0;

              return (
                <div key={epic.id} className="atlas-chart__row">
                  <div className="atlas-chart__rail">
                    {/* `.atlas-chart__rail-slot` is a plain in-flow wrapper
                        on desktop/down-mode (no CSS rule targets it outside
                        the mobile layer) — it only becomes the POC overlay's
                        positioned ancestor at <=720px (styles.css), so the
                        overlay sits exactly over `.atlas-rail-card`'s own
                        box rather than the full-width sticky rail band
                        around it. */}
                    <div className="atlas-chart__rail-slot">
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

                      {/* Mobile-across POC overlay: covers the rail card in
                          place so tapping a trail marker previews the child
                          without leaving the row or opening the full
                          drawer. */}
                      {showPreview && previewChild && (
                        <div
                          className={
                            "atlas-preview-card" +
                            ` atlas-rail-card--accent-${accentKeyForCard(previewChild)}`
                          }
                        >
                          <button
                            type="button"
                            className="atlas-preview-card__close"
                            aria-label="Close preview"
                            onClick={() => setPreviewChildId(null)}
                          >
                            ✕
                          </button>
                          <div className="atlas-preview-card__top">
                            <span className="atlas-preview-card__id">{previewChild.id}</span>
                            {previewStars > 0 && (
                              <span className="atlas-preview-card__stars" aria-hidden="true">
                                {[0, 1, 2, 3].map((s) => (
                                  <StarIcon
                                    key={s}
                                    filled={s < previewStars}
                                    className={
                                      "atlas-preview-card__star " +
                                      (s < previewStars
                                        ? "atlas-preview-card__star--filled"
                                        : "atlas-preview-card__star--empty")
                                    }
                                  />
                                ))}
                              </span>
                            )}
                          </div>
                          <div className="atlas-preview-card__title">{previewChild.title}</div>
                          <div className="atlas-preview-card__status">
                            {bannerLabelForCard(previewChild)}
                          </div>
                          {previewChild.checklist.length > 0 && (
                            <div className="atlas-preview-card__checklist">
                              {previewDone}/{previewChild.checklist.length} done
                            </div>
                          )}
                        </div>
                      )}
                    </div>
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
                      onOpenCard={trailOnOpenCard}
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
