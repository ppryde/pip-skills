import { useEffect, useMemo, useRef, useState } from "react";
import type { Board, BoardCard } from "../api/types";
import { accentKeyForCard } from "../board/cardAccent";
import {
  computeAxisTicks,
  computeWindow,
  formatDateStamp,
  parseCalendarDate,
  pctForDate,
} from "../board/atlasGeometry";
import AtlasRailCard from "./AtlasRailCard";
import AtlasTrail from "./AtlasTrail";

export interface EpicAtlasProps {
  board: Board;
  /** Chunk 5 precedent (Board/EpicCard): clicking a rail card body opens
   * the existing detail drawer for that card — App's drawer, unchanged. */
  onOpenCard: (id: string) => void;
  /** Optional override for tests/stories. Production call sites pass
   * nothing, so `today` is genuinely "now" at this component-boundary
   * render — see atlasGeometry's doc comment for why the pure modules
   * beneath this page never do that themselves. */
  today?: Date;
}

const EMPTY_STATE_COPY = "No sagas yet — give a quest children and it becomes a campaign.";

/**
 * Epic Atlas page (WF-086) — a gantt-esque sibling view to the board, one
 * campaign-trail row per epic. Filters `board.cards` to `is_epic` cards that
 * ALSO carry a non-null `rollup` (an epic minted without one yet has no
 * done/total to plot); every other epic/child grouping is a plain
 * `cards.filter(c => c.parent === epic.id)`, no new endpoints.
 *
 * `.atlas-chart` is the page's ONE horizontal scroller (the `725ddea`
 * mobile invariant) — no extra scroll wrapper around it.
 */
function EpicAtlas({ board, onOpenCard, today: todayOverride }: EpicAtlasProps) {
  // `useState(() => ...)` (lazy initializer) so a component-boundary
  // `new Date()` is captured exactly once at mount, not re-evaluated (and
  // silently drifting) on every render — see the `today` prop's doc comment.
  const [today] = useState(() => todayOverride ?? new Date());
  const chartRef = useRef<HTMLDivElement>(null);
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(new Set());

  const cardsById = useMemo(() => {
    const map = new Map<string, BoardCard>();
    for (const c of board.cards) map.set(c.id, c);
    return map;
  }, [board.cards]);

  const epics = useMemo(
    () =>
      board.cards
        .filter((c) => c.is_epic && c.rollup !== null)
        .sort((a, b) => parseCalendarDate(a.created).getTime() - parseCalendarDate(b.created).getTime()),
    [board.cards]
  );

  const childrenByEpic = useMemo(() => {
    const map = new Map<string, BoardCard[]>();
    for (const epic of epics) {
      map.set(epic.id, board.cards.filter((c) => c.parent === epic.id));
    }
    return map;
  }, [epics, board.cards]);

  const dateWindow = useMemo(
    () =>
      computeWindow(
        epics.map((epic) => ({
          created: epic.created,
          updated: epic.updated,
          children: (childrenByEpic.get(epic.id) ?? [])
            .filter((c) => c.status === "done")
            .map((c) => ({ updated: c.updated })),
        })),
        today
      ),
    [epics, childrenByEpic, today]
  );

  const ticks = useMemo(() => computeAxisTicks(dateWindow), [dateWindow]);
  const todayPct = pctForDate(today, dateWindow);

  // Mount-only centring (HANDOFF: the axis starts scrolled to today, not to
  // the trailhead) — plain `scrollLeft` assignment, jsdom-safe, deliberately
  // NOT scrollIntoView. Clamped to >= 0 so a today-near-the-window-start
  // board never requests a negative scroll.
  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;
    const target = (todayPct / 100) * el.scrollWidth - el.clientWidth / 2;
    el.scrollLeft = Math.max(0, target);
    // Deliberately mount-only (empty deps) — HANDOFF centres the axis on
    // today once, at open; it isn't meant to keep re-snapping the user's
    // own scroll position back to today on every board refresh.
  }, []);

  function toggleExpand(id: string) {
    setExpandedEpics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function blockedOnFor(epic: BoardCard): string[] {
    return epic.depends_on.filter((depId) => cardsById.get(depId)?.status !== "done");
  }

  return (
    <div className="atlas-chart" ref={chartRef}>
      {epics.length === 0 ? (
        <p className="atlas-chart__empty">{EMPTY_STATE_COPY}</p>
      ) : (
        <>
          <div className="atlas-chart__axis">
            <div className="atlas-chart__axis-rail" aria-hidden="true" />
            <div className="atlas-chart__axis-days">
              {ticks.map((tick, i) => (
                <span
                  key={i}
                  className="atlas-chart__tick"
                  style={{ left: `${pctForDate(tick, dateWindow)}%` }}
                >
                  {formatDateStamp(tick)}
                </span>
              ))}
            </div>
          </div>

          <div className="atlas-chart__rows">
            {epics.map((epic) => {
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
                  <div className="atlas-chart__lane">
                    <AtlasTrail
                      card={epic}
                      rollup={rollup}
                      childCards={childCards}
                      today={today}
                      dateWindow={dateWindow}
                      accentKey={accentKey}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Spans the whole field (HANDOFF) — ported verbatim from the
              prototype's `today.style.left` calc so it respects whatever
              `--rail` width the later styling chunk declares. */}
          <div
            className="atlas-chart__today"
            style={{ left: `calc(var(--rail) + (100% - var(--rail)) * ${todayPct / 100})` }}
          >
            <span className="atlas-chart__today-flag">⚑ TODAY</span>
          </div>
        </>
      )}
    </div>
  );
}

export default EpicAtlas;
