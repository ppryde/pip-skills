import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  DndContext,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import type { Board as BoardModel } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import type { PartyMember } from "../board/party";
import { collapseStagesForMobile, groupIntoLanes } from "../board/layout";
import { groupChildrenByEpic } from "../board/epicChildren";
import { laneIconKey } from "../board/laneIcons";
import { useMediaQuery } from "../board/useMediaQuery";
import { DRAG_SENSOR_DESCRIPTORS } from "../board/dragSensors";
import { locateDropTarget, resolveDrop } from "../board/dragPlan";
import { runDropPlan } from "../board/runDropPlan";
import Lane from "./Lane";
import LaneIconNav from "./LaneIconNav";
import PartyColumn from "./PartyColumn";

export interface BoardProps {
  board: BoardModel;
  showArchive: boolean;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Chunk 5: clicking a tile body opens the detail drawer for that card. */
  onOpenCard: (id: string) => void;
  /** WF-008 C4: pauses useBoard's 5s background poll for the duration of a
   *  drag — wired to dnd-kit's onDragStart/onDragEnd/onDragCancel below. */
  setDragActive: UseBoardResult["setDragActive"];
  /** WF-029: rendered by PartyColumn, the scroll row's rightmost item. */
  party: PartyMember[];
  /** WF-031 branch filter: `null` clears dim/spotlight everywhere; passed
   * straight through to every Lane (cards) and PartyColumn (agents). */
  activeBranch: string | null;
  /** WF-042: `context.threshold`, passed straight through to PartyColumn
   * for its per-row near-threshold cue — App.tsx's single source, no
   * re-derivation here. */
  threshold: number | null;
  /** F3/WF-061: the filter bar's live result — every card id that survives
   * `visibleCardIds(board.cards, filter)` in App. Applied before lane
   * placement below; sprints/quarantined/party are untouched by it (the
   * filter bar only ever curates cards). */
  visibleIds: Set<string>;
  /** Task 6: ids currently within their 60s post-icon-change glow window
   * (App.tsx's `useIconKeyGlow`) — passed straight through to every Lane. */
  glowingIds: Set<string>;
}

/**
 * Horizontally-scrollable lane container. Renders exactly the lanes
 * `groupIntoLanes` produces — Parked/Done/Archive sit at the right of the
 * row (see styles.css), and the Abandoned lane is only rendered when the
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
function Board({
  board,
  showArchive,
  mutate,
  inFlight,
  onOpenCard,
  setDragActive,
  party,
  activeBranch,
  threshold,
  visibleIds,
  glowingIds,
}: BoardProps) {
  // Filtered once, up front — every lane/epic-grouping consumer below reads
  // this instead of `board.cards` directly. `visibleCardIds` (cardFilter.ts)
  // already resolves epic/children membership (a matched epic pulls its
  // children in with it), so this is a plain id-set filter, not a re-derive.
  const visibleCards = useMemo(
    () => board.cards.filter((c) => visibleIds.has(c.id)),
    [board.cards, visibleIds]
  );
  const lanes = useMemo(() => groupIntoLanes(visibleCards), [visibleCards]);

  // Epic children (task 3/4, epic board identity): threaded straight through
  // to Lane -> EpicCard's inline sub-quest log and blocked-child resolution.
  // Derived from the WHOLE board (`board.cards`), not `visibleCards` — a
  // filtered-out child should still count toward its epic's quest log even
  // if the filter bar currently hides it from its own lane.
  const childrenByEpic = useMemo(
    () => groupChildrenByEpic(board.cards),
    [board.cards]
  );
  const cardsById = useMemo(
    () => new Map(board.cards.map((c) => [c.id, c])),
    [board.cards]
  );

  // WF-085 in-progress lane: collapse the 7 `kind:"stage"` lanes into ONE
  // "In Progress" lane (`collapseStagesForMobile`, board/layout.ts) — fewer,
  // mostly-empty columns. As of the user's "hide the additional columns for
  // now on desktop" request this is applied on EVERY viewport (was mobile-
  // only), so desktop and mobile both show the collapsed set (Backlog / In
  // Progress / Parked / Done / Abandoned). `displayLanes` (NOT `lanes`) is
  // what the swipe track, the icon-nav, AND the desktop columns render from,
  // so they can never disagree about which lanes exist. Drag/drop below
  // deliberately keeps using `lanes` (the real per-stage layout), never
  // `displayLanes` — see `handleDragEnd`'s comment — so the stage granularity
  // is preserved under the hood for when the columns come back.
  const isMobile = useMediaQuery("(max-width:720px)");
  const displayLanes = useMemo(
    () => collapseStagesForMobile(lanes),
    [lanes]
  );

  const [highlightedEpicId, setHighlightedEpicId] = useState<string | null>(
    null
  );
  const [dragToast, setDragToast] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(DRAG_SENSOR_DESCRIPTORS[0].sensor, DRAG_SENSOR_DESCRIPTORS[0].options),
    useSensor(DRAG_SENSOR_DESCRIPTORS[1].sensor, DRAG_SENSOR_DESCRIPTORS[1].options),
    useSensor(DRAG_SENSOR_DESCRIPTORS[2].sensor, DRAG_SENSOR_DESCRIPTORS[2].options)
  );

  const toggleEpicHighlight = (id: string) => {
    setHighlightedEpicId((current) => (current === id ? null : id));
  };

  // Click-away to dismiss the epic highlight: while an epic is highlighted, a
  // pointerdown anywhere OUTSIDE that epic's own card clears it (same dismiss
  // idiom as InfoTooltip). A pointerdown WITHIN the highlighted epic — its
  // expand toggle, body, drag handle — is left to that card's own handlers,
  // so the expand button can still toggle it off directly.
  useEffect(() => {
    if (!highlightedEpicId) return;
    function onPointerDown(e: MouseEvent) {
      const target = e.target as HTMLElement | null;
      if (target?.closest(`[data-card-id="${highlightedEpicId}"]`)) return;
      setHighlightedEpicId(null);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [highlightedEpicId]);

  const visibleLanes = displayLanes.filter(
    (lane) => lane.kind !== "archive" || showArchive
  );

  // WF-085a/mobile-v2: mobile icon-nav (LaneIconNav) + swipe-lane
  // active-sync. The nav lists EVERY lane in `visibleLanes` (same order,
  // same `.key`), including empty stage lanes, for completeness/even
  // spacing — but an empty lane's box renders `disabled`/faded and is NOT
  // a tap target (LaneIconNav.tsx keys this off `count === 0`), because the
  // swipe track itself does NOT give an empty lane a real pane: `.lane--
  // empty` is a thin, non-snapping sliver (see the mobile media block) —
  // there's nowhere for a tap-jump to land. Always rendered — CSS
  // (`@media (max-width:720px)`) is what actually shows the strip / turns
  // `.board` into a snap-scroller; on desktop the listener below just never
  // fires because `.board` itself never scrolls there.
  const navLanes = useMemo(
    () =>
      visibleLanes.map((lane) => ({
        key: lane.key,
        label: lane.label,
        count: lane.cards.length,
        accent: laneIconKey(lane),
      })),
    [visibleLanes]
  );

  const trackRef = useRef<HTMLDivElement | null>(null);
  const [activeLaneKey, setActiveLaneKey] = useState<string>(
    navLanes.find((lane) => lane.count > 0)?.key ?? navLanes[0]?.key ?? ""
  );

  // The filter bar / archive toggle can remove the currently-active lane
  // from `navLanes` out from under us (e.g. a search that no longer matches
  // its cards, or the active lane's last card leaves it empty) — fall back
  // to the first remaining NON-EMPTY lane, never an empty one: its nav icon
  // is disabled/non-interactive (no swipe pane to sync against), so it must
  // never be left as the "active" pill either.
  useEffect(() => {
    if (navLanes.length === 0) return;
    const current = navLanes.find((lane) => lane.key === activeLaneKey);
    if (!current || current.count === 0) {
      const fallback = navLanes.find((lane) => lane.count > 0) ?? navLanes[0];
      setActiveLaneKey(fallback.key);
    }
  }, [navLanes, activeLaneKey]);

  // Scroll-sync: on every scroll of the lane track, find whichever
  // `[data-lane-key]` pane's centre sits nearest the track's own centre and
  // make that the active lane. Cheap enough (≤11 lanes) to run unthrottled
  // on scroll — no rAF/debounce needed at this scale. Only NON-EMPTY lanes
  // are candidates (`navLaneKeys`) — an empty lane's sliver can still be
  // nearest-centre mid-swipe (it's not a snap-stop), but it must never
  // become the active key since its nav icon is disabled/faded, not a real
  // target to light up.
  const navLaneKeys = useMemo(
    () => new Set(navLanes.filter((lane) => lane.count > 0).map((lane) => lane.key)),
    [navLanes]
  );

  const handleTrackScroll = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const trackRect = track.getBoundingClientRect();
    const trackCenter = trackRect.left + trackRect.width / 2;

    let nearestKey: string | null = null;
    let nearestDistance = Infinity;
    track.querySelectorAll<HTMLElement>("[data-lane-key]").forEach((el) => {
      const key = el.dataset.laneKey;
      if (!key || !navLaneKeys.has(key)) return;
      const rect = el.getBoundingClientRect();
      const center = rect.left + rect.width / 2;
      const distance = Math.abs(center - trackCenter);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestKey = key;
      }
    });

    if (nearestKey && nearestKey !== activeLaneKey) {
      setActiveLaneKey(nearestKey);
    }
  }, [activeLaneKey, navLaneKeys]);

  // Nav-jump: tapping an icon both sets the active pill immediately (no
  // waiting on the scroll-settle above) and centres that lane's pane in the
  // HORIZONTAL track — mirrors the approved prototype's tap-to-jump.
  const handleNavJump = useCallback((key: string) => {
    setActiveLaneKey(key);
    const track = trackRef.current;
    const target = track?.querySelector<HTMLElement>(
      `[data-lane-key="${key}"]`
    );
    if (!track || !target) return;
    // Scroll ONLY the track's own horizontal position. This used to call
    // `target.scrollIntoView({ inline: "center", block: "nearest" })`, but the
    // `block` axis also scrolled the vertical `.board-region`, pushing the
    // tapped lane's header up out of view (a tap "jumped past" the header to
    // the first card). Nudging `scrollLeft` by the centre-to-centre delta
    // leaves the page's vertical position — and the header — untouched.
    // Guarded: jsdom doesn't implement `scrollTo` (the tests polyfill it), so
    // an unguarded call would throw there.
    if (typeof track.scrollTo !== "function") return;
    const trackRect = track.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const delta =
      targetRect.left +
      targetRect.width / 2 -
      (trackRect.left + trackRect.width / 2);
    track.scrollTo({ left: track.scrollLeft + delta, behavior: "smooth" });
  }, []);

  // Item 8: on mobile, `.board-region`'s page-scroll length must follow the
  // ACTIVE lane's own content height, not the tallest lane in the row.
  // `.board` is a single-line flex row of lanes (`align-items: flex-start`,
  // base rule) — that stops SHORTER lanes being visually stretched, but the
  // flex LINE's own auto height (and so `.board`'s) is still the max of
  // every lane in it regardless of align-items, since the line has to be
  // tall enough to contain its tallest item. So `.board-region`'s vertical
  // scroll range stayed pinned to the tallest lane even while swiped to a
  // short one — you could scroll the page down into visually empty space
  // below a short lane's last card. Measuring the currently-active lane's
  // pane and pinning `.board`'s OWN height to it (mobile only — see the
  // inline style below, and `overflow-y: hidden` on `.board` in the mobile
  // CSS block that actually clips the other, now-taller siblings so they
  // stop contributing to the scrollable region) makes a short lane's page
  // scroll stop exactly at its own last card, and a tall lane's full card
  // list stays reachable via the same page scroll as before. Desktop never
  // sets this (gated on `isMobile`), so `.board`'s CSS `height: 100%` there
  // is untouched.
  const [activeLaneHeight, setActiveLaneHeight] = useState<number | null>(
    null
  );

  useLayoutEffect(() => {
    if (!isMobile) {
      setActiveLaneHeight(null);
      return;
    }
    const track = trackRef.current;
    if (!track) return;

    const pane = track.querySelector<HTMLElement>(
      `[data-lane-key="${activeLaneKey}"]`
    );
    if (!pane) return;

    const measure = () => setActiveLaneHeight(pane.scrollHeight);
    measure();

    // Re-measure when the active lane's OWN content changes size (a card
    // added/removed/expanded) without needing the active lane to change —
    // jsdom (unlike every real browser) has no ResizeObserver, so this is
    // a no-op (not a crash) under the component tests, same guard pattern
    // as the `scrollIntoView` check in `handleNavJump` above.
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(pane);
    return () => ro.disconnect();
  }, [isMobile, activeLaneKey, displayLanes]);

  const handleDragStart = useCallback(() => {
    setDragActive(true);
  }, [setDragActive]);

  // dnd-kit calls onDragCancel (not onDragEnd) when a drag is aborted (e.g.
  // Escape) — without this the poll pause would never clear.
  const handleDragCancel = useCallback(() => {
    setDragActive(false);
  }, [setDragActive]);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setDragActive(false);
      const { active, over } = event;
      if (!over) return;

      const draggedId = String(active.id);
      const dragged = board.cards.find((c) => c.id === draggedId);
      if (!dragged) return;

      // Deliberately `lanes` (the real per-stage layout), never
      // `displayLanes` — the mobile "in-progress" lane is a view/navigation
      // construct only, with no single stage of its own, so it must never
      // be wired as a stage-change drop target. Its droppable id
      // ("in-progress") never matches any REAL lane key here, so a drop on
      // its background resolves to `targetLane: undefined` below and
      // no-ops harmlessly; a drop on a CARD inside it still resolves via
      // that card's own real stage lane, same as desktop. Either way: no
      // crash, and desktop drag/drop (the real 7 stage lanes) is untouched.
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
    [board.cards, lanes, mutate, setDragActive]
  );

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      {/* WF-085: mobile-only icon-nav strip, rendered above the lane track.
          Desktop hides it entirely via CSS — see `.lane-icon-nav` in
          styles.css, gated at `@media (max-width:720px)`. */}
      <LaneIconNav lanes={navLanes} activeKey={activeLaneKey} onJump={handleNavJump} />
      <div
        className="board"
        ref={trackRef}
        onScroll={handleTrackScroll}
        // Item 8 (mobile only — see the `activeLaneHeight` effect above):
        // pins `.board`'s box to the active lane's own content height so
        // `.board-region`'s page scroll can't run past it. `undefined`
        // whenever not mobile/not yet measured leaves the CSS `height`
        // rule (desktop's `100%`, or mobile's `auto` fallback before the
        // first layout effect run) in full control — never an empty
        // style attribute on desktop.
        style={
          isMobile && activeLaneHeight != null
            ? { height: `${activeLaneHeight}px` }
            : undefined
        }
      >
        {dragToast && (
          <div className="board-toast" role="status">
            {dragToast}
            {/* WF-097 follow-up: bare `<button>`, NOT `<Button>` —
                `.board-toast__dismiss` is a borderless underline text-link
                inside the toast (inherits the toast's own colour), not a
                `.qb-btn` Role-A button; the primitive's chrome would be wrong
                here. */}
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
            activeBranch={activeBranch}
            glowingIds={glowingIds}
            childrenByEpic={childrenByEpic}
            cardsById={cardsById}
            // F10 editable colour registry (WF-067) — straight off the
            // board payload's `label_colors`, threaded to every tile's
            // LabelChips via Lane -> CardTile/EpicCard -> TileShell.
            colorRegistry={board.label_colors}
          />
        ))}
        {/* Rightmost item in the scroll row (HANDOFF §Board) — the flex row
            puts it at the tail for free, no extra positioning needed. */}
        <PartyColumn party={party} activeBranch={activeBranch} threshold={threshold} />
      </div>
    </DndContext>
  );
}

export default Board;
