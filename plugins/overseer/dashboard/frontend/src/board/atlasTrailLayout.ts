/**
 * Progress-trail geometry for the Epic Atlas (WF-086 v2 revision) — see
 * `docs/design/epic-atlas/HANDOFF.md`'s "Trail geometry" section. Replaces
 * v1's date-axis trails: a child's position on the trail is now driven
 * purely by cumulative COMPLEXITY (weight), ordered done → in-progress →
 * todo, on ONE shared px-per-weight scale across every visible epic — the
 * heaviest saga spans the lane, lighter sagas end genuinely short.
 *
 * Every function here is pure (no DOM, no dates) so the whole layout is
 * unit-testable without rendering anything — `AtlasTrail.tsx` is a thin
 * SVG-painting layer over this module's output.
 */
import type { BoardCard, Status } from "../api/types";
import { rarityStars } from "./rarityStars";

/** The walled-village trailhead icon's own rendered size — HANDOFF (user
 * amendment): "~28-32px ... it is a town after all", deliberately GRANDER
 * than the other ~20px trail markers (`MARKER_SIZE_PX` in AtlasTrail.tsx/
 * AtlasTrailVertical.tsx). */
export const TRAILHEAD_ICON_SIZE_PX = 30;
/** Clearance beyond the trailhead icon before the trail's first segment
 * starts — keeps the icon clear of the rail/card on one side and the
 * trail's own content on the other. */
export const TRAILHEAD_PADDING_PX = 14;
/** H_LEFT_PAD in the prototype — reserve at the lane's left edge for the
 * trailhead (walled-village) icon, clear of the rail column. Derived from
 * the icon's own size + padding (same named-constant discipline as
 * `BEAST_RESERVE_PX` below) rather than a bare literal, so a bigger icon
 * can never end up short of clearance again. */
export const TRAILHEAD_RESERVE_PX = TRAILHEAD_ICON_SIZE_PX + TRAILHEAD_PADDING_PX;
/** Fixed offset from a trail's true end (H_LEFT_PAD + totalWeight *
 * pxPerWeight) to the beast's anchor point. */
export const BEAST_ANCHOR_OFFSET_PX = 26;
/** BeastFace's actual rendered footprint (viewBox 0 0 50 50, drawn at
 * width={48} height={48} — see BeastFace.tsx) — the beast's own doodle
 * extends this far past whichever point it's anchored/translated to. */
export const BEAST_ICON_SIZE_PX = 48;
/** Reserve at the lane's far edge (right in Across mode, bottom in Down
 * mode) for the beast doodle. Impl-review round 1 finding: HANDOFF's plain
 * "64" undersizes this — BEAST_ANCHOR_OFFSET_PX(26) + the beast's own
 * BEAST_ICON_SIZE_PX(48) = 74 > 64, so a 64px reserve clips the bottom of
 * every Down-mode beast by 10px and forces Across mode into ad-hoc
 * per-caller clamps that drift the heaviest epic's beast off the HANDOFF
 * anchor formula. Deriving this from the two other named constants (not a
 * bare literal) is what makes every clamp/content-height computed from it
 * — AtlasTrail.tsx's `width - BEAST_ICON_SIZE_PX` clamp, AtlasTrailVertical
 * .tsx's content-height sizing — actually agree with each other. */
export const BEAST_RESERVE_PX = BEAST_ANCHOR_OFFSET_PX + BEAST_ICON_SIZE_PX;
/** Usable trail width never collapses below this, however narrow the lane
 * gets (matches the prototype's floor). */
export const MIN_USABLE_PX = 40;
/** Gap the dotted line leaves on each side of a waypoint/boundary marker
 * (HANDOFF: "~15px gaps"). */
export const WAYPOINT_GAP_PX = 15;
/** Gap the dotted line leaves around the mid-segment campfire marker
 * (HANDOFF: "12px campfire"). */
export const CAMPFIRE_GAP_PX = 12;
/** How far into the frozen in-progress child's own segment the campfire
 * sits (HANDOFF: "campfire at 78% of frozen segment"). */
export const CAMPFIRE_FRACTION = 0.78;

/** Maps a card's `complexity` (rarityStars' S/M/L/XL → 1-4 scale) onto its
 * trail weight. An unset/unrecognised complexity floors to 1 (never 0) —
 * a zero-weight child would collapse to a zero-length segment with nowhere
 * for its own marker to sit. */
export function weightOf(card: Pick<BoardCard, "complexity">): number {
  return rarityStars(card.complexity) || 1;
}

export type TrailStatusGroup = "done" | "in-progress" | "todo";

/** A child's trail STATUS GROUP, distinct from its literal `status` value.
 * `abandoned` shares `done`'s group (0) — "fell on the march" is how a
 * walked quest sometimes ends, not a fourth stage after todo, so it
 * interleaves with done purely by board `order` (see `orderChildrenForTrail`).
 *
 * `blocked` is deliberately NOT its own group here (HANDOFF: "Blocked
 * (overlay state, not a status)") — the boulder overlay is computed
 * separately from open `depends_on` (see `openDependencies`), the same way
 * as the epic-level 🔒 chip; a card whose literal `status` happens to be
 * `"blocked"` hasn't done any real work yet, so it groups with `planned`
 * as `todo` (mirrors `layout.ts`'s board-lane precedent of folding
 * `"blocked"` into whichever real bucket it'd otherwise belong to). `parked`
 * is likewise not expected on a CHILD card in practice (parking is an
 * epic-level "the whole saga is on hold" state) but falls back to `todo`
 * for the same not-yet-walked reason if it ever occurs. */
const STATUS_GROUP: Record<Status, TrailStatusGroup> = {
  done: "done",
  abandoned: "done",
  "in-flight": "in-progress",
  planned: "todo",
  blocked: "todo",
  parked: "todo",
};

const GROUP_RANK: Record<TrailStatusGroup, number> = { done: 0, "in-progress": 1, todo: 2 };

export function statusGroupOf(card: Pick<BoardCard, "status">): TrailStatusGroup {
  return STATUS_GROUP[card.status];
}

/** Orders children done → in-progress → todo (abandoned interleaved with
 * done), then by board `order` within each group — dragging on the board
 * reorders the ahead-trail. Returns a new array; never mutates `children`. */
export function orderChildrenForTrail(children: BoardCard[]): BoardCard[] {
  return [...children].sort((a, b) => {
    const rankDiff = GROUP_RANK[statusGroupOf(a)] - GROUP_RANK[statusGroupOf(b)];
    if (rankDiff !== 0) return rankDiff;
    return a.order - b.order;
  });
}

/** `usable = max(laneWidth − beast reserve − trailhead reserve, 40)`. */
export function laneUsableWidth(laneWidth: number): number {
  return Math.max(laneWidth - BEAST_RESERVE_PX - TRAILHEAD_RESERVE_PX, MIN_USABLE_PX);
}

export function totalWeight(children: BoardCard[]): number {
  return children.reduce((sum, c) => sum + weightOf(c), 0);
}

/** The ONE shared px-per-weight scalar (HANDOFF: "recomputed each render")
 * — usable width divided by the HEAVIEST epic's total weight, across every
 * currently-visible epic. Floors the heaviest weight at 1 so an
 * all-childless board never divides by zero. */
export function globalPxPerWeight(totalWeights: number[], usable: number): number {
  const heaviest = Math.max(1, ...totalWeights);
  return usable / heaviest;
}

export interface TrailSegment {
  child: BoardCard;
  start: number;
  end: number;
}

/** Cumulative-weight segment layout for one epic's ALREADY-ORDERED
 * children, on the shared `pxPerWeight` scale — NOT normalized to this
 * epic's own total, which is what makes cross-row length comparisons real. */
export function computeSegments(orderedChildren: BoardCard[], pxPerWeight: number): TrailSegment[] {
  let cum = 0;
  return orderedChildren.map((child) => {
    const start = TRAILHEAD_RESERVE_PX + cum * pxPerWeight;
    cum += weightOf(child);
    const end = TRAILHEAD_RESERVE_PX + cum * pxPerWeight;
    return { child, start, end };
  });
}

/** An epic's trail end (true length, before the beast anchor offset) —
 * `H_LEFT_PAD + totalWeight(epic) * pxPerWeight`. */
export function trailEndX(epicTotalWeight: number, pxPerWeight: number): number {
  return TRAILHEAD_RESERVE_PX + epicTotalWeight * pxPerWeight;
}

export function beastAnchorX(trailEnd: number): number {
  return trailEnd + BEAST_ANCHOR_OFFSET_PX;
}

/** The done|in-progress boundary — where the party token (marching) or,
 * absent one, the trailhead itself stands: the last WALKED child's segment
 * end (done or abandoned, whichever came last in trail order), or
 * TRAILHEAD_RESERVE_PX if nothing's done yet. */
export function boundaryX(segments: TrailSegment[]): number {
  let boundary = TRAILHEAD_RESERVE_PX;
  for (const seg of segments) {
    if (statusGroupOf(seg.child) === "done") boundary = seg.end;
  }
  return boundary;
}

/** The frozen in-progress child's own segment (a parked epic's camped
 * quest) — the FIRST in-progress-group segment in trail order, or null if
 * there is none. */
export function frozenSegment(segments: TrailSegment[]): TrailSegment | null {
  return segments.find((seg) => statusGroupOf(seg.child) === "in-progress") ?? null;
}

/** Campfire x — 78% into the frozen in-progress child's own segment,
 * falling back to the done|next boundary if there's no in-progress child
 * to freeze on. */
export function campfireX(segments: TrailSegment[]): number {
  const frozen = frozenSegment(segments);
  if (!frozen) return boundaryX(segments);
  return frozen.start + (frozen.end - frozen.start) * CAMPFIRE_FRACTION;
}

export interface MarkerCut {
  at: number;
  radius: number;
}

/** Interval-subtraction: trims `[x0, x1]` around each marker cut so the
 * dotted line stops short on each side of a marker rather than running
 * beneath it (HANDOFF: "markers interrupt the line"). Ported from the
 * prototype's `trimForMarkers`. Sub-intervals of 0.5px or less are dropped
 * (a marker gap wider than the segment itself). */
export function trimSegmentForMarkers(x0: number, x1: number, cuts: MarkerCut[]): [number, number][] {
  let ranges: [number, number][] = [[x0, x1]];
  for (const { at, radius } of cuts) {
    const cutStart = at - radius;
    const cutEnd = at + radius;
    ranges = ranges.flatMap(([a, b]): [number, number][] => {
      if (cutEnd <= a || cutStart >= b) return [[a, b]];
      const out: [number, number][] = [];
      if (a < cutStart) out.push([a, cutStart]);
      if (cutEnd < b) out.push([cutEnd, b]);
      return out;
    });
  }
  return ranges.filter(([a, b]) => b - a > 0.5);
}

/** `depends_on` targets that are not (yet) done — the same underlying
 * "blocked" signal as the epic-level 🔒 chip (HANDOFF's Data mapping: "open
 * depends_on (non-done targets)"), reused here for the child boulder
 * overlay's reason. A dependency id with no matching card on the board
 * (dangling) counts as open — there's no evidence it's done. */
export function openDependencies(
  card: Pick<BoardCard, "depends_on">,
  cardsById: Map<string, BoardCard>
): string[] {
  return card.depends_on.filter((id) => cardsById.get(id)?.status !== "done");
}

/** Vanquished-epics toolbar toggle (HANDOFF): hidden (default) filters
 * done epics out entirely; shown, they sort LAST, every other epic keeping
 * its relative order — `Array.prototype.sort` is guaranteed stable (ES2019+),
 * so this never needs to track original indices itself. Trail wobble seeds
 * (`seedFor(card.id)`) are already keyed on the card's own id rather than
 * its array position, so re-sorting here can never re-wobble a surviving
 * trail either — no extra bookkeeping needed for that HANDOFF requirement. */
export function orderEpicsForDisplay(epics: BoardCard[], hideVanquished: boolean): BoardCard[] {
  if (hideVanquished) return epics.filter((e) => e.status !== "done");
  return [...epics].sort((a, b) => Number(a.status === "done") - Number(b.status === "done"));
}
