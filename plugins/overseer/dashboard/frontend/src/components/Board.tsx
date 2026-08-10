import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import type { Board as BoardModel } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import type { PartyMember } from "../board/party";
import { groupIntoLanes } from "../board/layout";
import { laneIconKey } from "../board/laneIcons";
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

  const visibleLanes = lanes.filter(
    (lane) => lane.kind !== "archive" || showArchive
  );

  // WF-085a: mobile icon-nav (LaneIconNav) + swipe-lane active-sync. The nav
  // lists only NON-EMPTY lanes from `visibleLanes` (same order, same `.key`
  // for whichever lanes it does show) — empty stage lanes are deliberately
  // excluded. An empty lane isn't a swipe snap-stop (`.lane--empty {
  // scroll-snap-align: none }` in styles.css), so a nav icon pointing at one
  // would tap-jump to a target the swipe track can't settle on. The swipe
  // track itself still renders every `visibleLanes` entry (empty lanes as
  // the thin `.lane--empty` sliver) — only this nav strip filters. Always
  // rendered — CSS (`@media (max-width:720px)`) is what actually shows the
  // strip / turns `.board` into a snap-scroller; on desktop the listener
  // below just never fires because `.board` itself never scrolls there.
  const navLanes = useMemo(
    () =>
      visibleLanes
        .filter((lane) => lane.cards.length > 0)
        .map((lane) => ({
          key: lane.key,
          label: lane.label,
          count: lane.cards.length,
          accent: laneIconKey(lane),
        })),
    [visibleLanes]
  );

  const trackRef = useRef<HTMLDivElement | null>(null);
  const [activeLaneKey, setActiveLaneKey] = useState<string>(
    navLanes[0]?.key ?? ""
  );

  // The filter bar / archive toggle can remove the currently-active lane
  // from `navLanes` out from under us (e.g. a search that no longer matches
  // its cards, or the active lane's last card leaves it empty) — fall back
  // to the first remaining NON-EMPTY lane rather than pointing the nav's
  // active pill at a lane the strip no longer shows an icon for.
  useEffect(() => {
    if (navLanes.length === 0) return;
    if (!navLanes.some((lane) => lane.key === activeLaneKey)) {
      setActiveLaneKey(navLanes[0].key);
    }
  }, [navLanes, activeLaneKey]);

  // Scroll-sync: on every scroll of the lane track, find whichever
  // `[data-lane-key]` pane's centre sits nearest the track's own centre and
  // make that the active lane. Cheap enough (≤11 lanes) to run unthrottled
  // on scroll — no rAF/debounce needed at this scale. Only panes the nav
  // actually shows an icon for are candidates (`navLaneKeys`) — an empty
  // lane can still be nearest-centre mid-swipe (it's a thin sliver, not a
  // snap-stop), but it must never become the active key since no nav icon
  // exists to light up for it.
  const navLaneKeys = useMemo(
    () => new Set(navLanes.map((lane) => lane.key)),
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
  // waiting on the scroll-settle above) and scrolls that lane's pane to
  // the track's centre — mirrors the approved prototype's tap-to-jump.
  const handleNavJump = useCallback((key: string) => {
    setActiveLaneKey(key);
    const target = trackRef.current?.querySelector<HTMLElement>(
      `[data-lane-key="${key}"]`
    );
    // Guarded rather than a bare optional call: jsdom (unlike every real
    // browser) doesn't implement `scrollIntoView` at all — see Element.
    // prototype in test envs — so an unguarded call would throw in tests.
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    }
  }, []);

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
      <div className="board" ref={trackRef} onScroll={handleTrackScroll}>
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
            activeBranch={activeBranch}
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
