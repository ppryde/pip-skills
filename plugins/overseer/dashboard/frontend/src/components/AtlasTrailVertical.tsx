import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { BoardCard, Rollup } from "../api/types";
import { formatDateStamp, parseCalendarDate, seedFor } from "../board/atlasGeometry";
import {
  BEAST_ICON_SIZE_PX,
  CAMPFIRE_GAP_PX,
  TRAILHEAD_ICON_SIZE_PX,
  TRAILHEAD_RESERVE_PX,
  WAYPOINT_GAP_PX,
  beastAnchorX,
  boundaryX,
  campfireX,
  computeSegments,
  openDependencies,
  orderChildrenForTrail,
  statusGroupOf,
  totalWeight,
  trailEndX,
  trimSegmentForMarkers,
  weightOf,
} from "../board/atlasTrailLayout";
import { ARC_PX_PER_UNIT_SERPENTINE, serpentineTrail } from "../board/serpentineTrail";
import { beastFor } from "../board/beastName";
import { formatTokens } from "../board/formatTokens";
import BeastFace from "./BeastFace";

import trailheadIcon from "../assets/villages/icon_7.png";
import boulderIcon from "../assets/trail-icons/boulder.svg";
import campfireIcon from "../assets/trail-icons/campfire.png";
import abandonedIcon from "../assets/lane-icons/abandoned.png";

export interface AtlasTrailVerticalProps {
  card: BoardCard;
  rollup: Rollup;
  childCards: BoardCard[];
  cardsById: Map<string, BoardCard>;
  showNames: boolean;
  /** Opens the existing card detail drawer for a clicked trail name-tag
   * (todo or done) — mirrors AtlasTrail.tsx's own prop of the same name. */
  onOpenCard: (id: string) => void;
  accentKey?: string;
}

const DEFAULT_COLUMN_WIDTH = 280;
const MARKER_SIZE_PX = 20;
const NAME_TAG_TIER_OFFSET_PX = 16;

function weightLabel(child: BoardCard): string {
  return "★".repeat(weightOf(child));
}

/**
 * Down-mode's mirror of `AtlasTrail.tsx` — same per-status marker language
 * (done ✓, abandoned skull, AT HAND ring+pennant, faded todo + name-tags,
 * blocked boulder, campfire, party token, trailhead, beast), but marching
 * top->bottom as a wide SERPENTINE (HANDOFF's Down-mode user amendment,
 * 2026-08-11, re-amended for rounded turns) rather than a flat straight
 * drop — see `serpentineTrail.ts` for the curve geometry and why "same
 * weight = same length" holds in TRUE path-arc terms there.
 * `atlasTrailLayout.ts`'s scalar functions (computeSegments/boundaryX/
 * campfireX/trailEndX/beastAnchorX/trimSegmentForMarkers) are reused
 * UNCHANGED — they operate on a generic "distance along the trail" scalar,
 * which is now cumulative ARC LENGTH (fed `ARC_PX_PER_UNIT_SERPENTINE`
 * instead of Across mode's shared `pxPerWeight`) rather than a raw Y
 * coordinate. Every place that needs an actual SCREEN position calls
 * `t.pointAt(scalar)` for BOTH x and y together — never treats the raw
 * scalar as a Y coordinate directly (arc length exceeds vertical Y almost
 * everywhere, since the path also travels sideways).
 *
 * Kept as its own component rather than an orientation branch inside
 * AtlasTrail — the two scales (shared vs. flat-per-column) and axes are
 * different enough that folding them into one component would trade a
 * little duplication for a lot of conditional plumbing.
 */
function AtlasTrailVertical({
  card,
  rollup,
  childCards,
  cardsById,
  showNames,
  onOpenCard,
  accentKey,
}: AtlasTrailVerticalProps) {
  const colRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_COLUMN_WIDTH);

  useEffect(() => {
    const el = colRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const measured = entry.contentRect.width;
      setWidth(Number.isFinite(measured) && measured > 0 ? measured : DEFAULT_COLUMN_WIDTH);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const seed = seedFor(card.id);
  const beast = beastFor(card.id);

  const ordered = orderChildrenForTrail(childCards);
  const segments = computeSegments(ordered, ARC_PX_PER_UNIT_SERPENTINE);
  const epicTotalWeight = totalWeight(childCards);
  const trailEnd = trailEndX(epicTotalWeight, ARC_PX_PER_UNIT_SERPENTINE);
  const boundaryArc = boundaryX(segments);
  const campArc = campfireX(segments);

  const slain = card.status === "done";
  const parked = !slain && card.status === "parked";
  const marching = card.status === "in-flight";

  // Round 3 closing item (reviewer-d, Minor): serpentineTrail() builds a
  // sampled arc-length lookup table (2000 samples up to MAX_TABLE_Y_PX) on
  // every call — Down-mode's own scroll handler (EpicAtlas.tsx's
  // activeColumnHeight effect) fires renders constantly while scrolling,
  // so an unmemoized call here was rebuilding that table every single one
  // of those renders for no reason: `width` only changes on a real
  // ResizeObserver measurement and `seed` is derived from `card.id` (never
  // changes for a mounted instance) — same "no behavior change, memoize
  // recompute" call as `EpicAtlas.tsx`'s `useMemo`-wrapped derived values.
  const t = useMemo(() => serpentineTrail(Math.max(width, 1), seed), [width, seed]);

  const beastAnchorArc = beastAnchorX(trailEnd);
  const beastPoint = t.pointAt(beastAnchorArc);
  const beastX = beastPoint.x - BEAST_ICON_SIZE_PX / 2;
  const beastY = beastPoint.y;
  // The SVG's Y-extent (viewBox height) must clear the beast's own
  // rendered FOOTPRINT — computed directly in true Y pixels
  // (`beastY + BEAST_ICON_SIZE_PX`), not by advancing the ARC-LENGTH
  // scalar by `BEAST_RESERVE_PX` and converting that through `pointAt`.
  // Arc length and Y are NOT 1:1 here (`dy/d(arcLength) <= 1` almost
  // everywhere the serpentine travels sideways, often well under 1 near
  // the middle of a "cruise" leg) — advancing arc length by
  // `BEAST_RESERVE_PX` would under-reserve real vertical space and clip
  // the beast, reintroducing finding 1's original bug in arc-length form.
  const contentHeight = beastY + BEAST_ICON_SIZE_PX;

  const svgClassName = "atlas-trail__svg" + (accentKey ? ` atlas-trail__svg--accent-${accentKey}` : "");

  // "Flipping to whichever side has room on the current sweep" (HANDOFF) —
  // a point on the left half of the column has more room to its right
  // (before the sweep's own left turn-back), and vice versa.
  function roomySide(x: number): "left" | "right" {
    return x < width / 2 ? "right" : "left";
  }

  // Impl-review round 2, finding 1: `side` names WHICH SIDE OF THE MARKER
  // the tag should sit on — "right" means "render the tag to the marker's
  // right". The CSS property that ACHIEVES that is the OPPOSITE one:
  // anchoring via `left` grows the box rightward from that point (what a
  // "sits to the right" tag needs); anchoring via `right` grows it
  // leftward (what a "sits to the left" tag needs). The previous version
  // used `side` itself as the literal CSS property key — a "right"
  // placement set CSS `right:`, which anchors the box's RIGHT edge at the
  // marker and grows LEFTWARD, landing the tag on the CROWDED side, the
  // exact collision the flip exists to avoid.
  function sideOffset(side: "left" | "right", mx: number, extraOffsetPx: number): CSSProperties {
    return side === "right"
      ? { left: `${mx + 16 + extraOffsetPx}px` }
      : { right: `${width - mx + 16 + extraOffsetPx}px` };
  }

  const svgMarkers: ReactNode[] = [];
  const overlayTags: ReactNode[] = [];
  let todoTier = 0;
  // Independent tier counter for done-group tags (Feature 3) — same
  // rationale as AtlasTrail.tsx's own `doneTier`: the done and todo groups
  // sit on distinct stretches of the trail, so each alternates its own tags
  // off its own counter rather than sharing one running tally.
  let doneTier = 0;

  segments.forEach(({ child, end }, segmentIndex) => {
    const isLastChild = segmentIndex === segments.length - 1;
    const group = statusGroupOf(child);
    const { x: mx, y: my } = t.pointAt(end);
    const cleared = formatDateStamp(parseCalendarDate(child.updated));
    const side = roomySide(mx);
    const tagStyle: CSSProperties = {
      ...sideOffset(side, mx, 0),
      top: `${my}px`,
      transform: "translateY(-50%)",
    };

    if (group === "done") {
      if (child.status === "abandoned") {
        svgMarkers.push(
          <g
            key={child.id}
            className="atlas-trail__waypoint atlas-trail__waypoint--abandoned"
            transform={`translate(${mx - MARKER_SIZE_PX / 2}, ${my - MARKER_SIZE_PX / 2})`}
          >
            <image href={abandonedIcon} width={MARKER_SIZE_PX} height={MARKER_SIZE_PX} />
            <title>{`${child.title} — fell on the march · ${cleared}`}</title>
          </g>
        );
      } else {
        svgMarkers.push(
          <g key={child.id} className="atlas-trail__waypoint atlas-trail__waypoint--done">
            <circle cx={mx} cy={my} r={8} />
            <text className="atlas-trail__waypoint-check" x={mx} y={my + 3.5} textAnchor="middle">
              ✓
            </text>
            <title>{`${child.title} — cleared · ${cleared}`}</title>
          </g>
        );
      }
      // Feature 3: a greyed name-tag for a done (or abandoned) child, same
      // side-flip/tiering mechanism as the todo tag below (and the same
      // last-child beast-clearance suppression — an all-done/no-todo epic
      // can end its trail on a done child).
      if (showNames && !isLastChild) {
        const tier = doneTier % 2;
        doneTier++;
        const doneTagStyle: CSSProperties = {
          ...sideOffset(side, mx, tier * NAME_TAG_TIER_OFFSET_PX),
          top: `${my}px`,
          transform: "translateY(-50%)",
        };
        overlayTags.push(
          <button
            type="button"
            key={`${child.id}-tag`}
            className={
              "trail-tag trail-tag--done trail-tag--down " +
              (tier ? "trail-tag--tier-1" : "trail-tag--tier-0")
            }
            style={doneTagStyle}
            title={`${child.title} · ${weightLabel(child)}`}
            onClick={() => onOpenCard(child.id)}
          >
            {child.title}
          </button>
        );
      }
      return;
    }

    if (group === "in-progress") {
      const atHand = !parked;
      svgMarkers.push(
        <g
          key={child.id}
          className="atlas-trail__waypoint atlas-trail__waypoint--athand"
          // Mirrors AtlasTrail.tsx's own marker click — the pennant below
          // is suppressed on the trail's last child, leaving this marker as
          // the only AT HAND affordance in that case.
          onClick={() => onOpenCard(child.id)}
        >
          {atHand && <circle cx={mx} cy={my} r={14} className="at-hand-ring" />}
          <circle cx={mx} cy={my} r={10} className="atlas-trail__athand-dot" />
          <text x={mx} y={my + 3.5} textAnchor="middle" className="atlas-trail__athand-glyph">
            ◆
          </text>
          <title>
            {atHand
              ? `${child.title} — the quest at hand (since ${cleared})`
              : `${child.title} — frozen mid-quest (camped ${cleared})`}
          </title>
        </g>
      );
      // Round 3 closing item (completes round-2 finding 5 in Down mode,
      // which previously had NO suppression at all here — reviewer-c
      // measured 68.2% of realistic seed x weight combinations colliding
      // tag-with-beast, majority case not edge): the trail's last child
      // sits exactly BEAST_ANCHOR_OFFSET_PX from the beast on every trail
      // regardless of length, same as AtlasTrail.tsx's own todo tag/
      // pennant suppression. Marker + tooltip still always render; only
      // the floating pennant label suppresses.
      if (atHand && !isLastChild) {
        overlayTags.push(
          <button
            type="button"
            key={`${child.id}-pennant`}
            className="trail-tag atlas-trail__pennant--athand trail-tag--down"
            style={tagStyle}
            onClick={() => onOpenCard(child.id)}
          >
            ◆ AT HAND
          </button>
        );
      }
      return;
    }

    const openDeps = openDependencies(child, cardsById);
    const blocked = openDeps.length > 0;
    const tier = todoTier % 2;
    todoTier++;

    svgMarkers.push(
      <g
        key={child.id}
        className={
          "atlas-trail__waypoint atlas-trail__waypoint--todo" +
          (blocked ? " atlas-trail__waypoint--blocked" : "")
        }
      >
        {blocked ? (
          <image
            className="atlas-trail__boulder"
            href={boulderIcon}
            x={mx - MARKER_SIZE_PX / 2}
            y={my - MARKER_SIZE_PX / 2}
            width={MARKER_SIZE_PX}
            height={MARKER_SIZE_PX}
          />
        ) : (
          <circle cx={mx} cy={my} r={6} className="atlas-trail__todo-dot" />
        )}
        <title>
          {blocked
            ? `${child.title} — the way is barred · ${cardsById.get(openDeps[0])?.title ?? "blocked"}`
            : `${child.title} — ahead · ${weightLabel(child)}`}
        </title>
      </g>
    );

    // Round 3 closing item: same last-child beast-clearance suppression as
    // the AT-HAND pennant above (and AtlasTrail.tsx's own todo tag) — the
    // trail's last todo child's marker is exactly as beast-adjacent as any
    // other last child.
    if (showNames && !isLastChild) {
      const tierTagStyle: CSSProperties = {
        ...tagStyle,
        ...sideOffset(side, mx, tier * NAME_TAG_TIER_OFFSET_PX),
      };
      overlayTags.push(
        <button
          type="button"
          key={`${child.id}-tag`}
          className={
            "trail-tag trail-tag--todo trail-tag--down " +
            (blocked ? "trail-tag--blocked " : "") +
            (tier ? "trail-tag--tier-1" : "trail-tag--tier-0")
          }
          style={tierTagStyle}
          title={`${child.title} · ${weightLabel(child)}`}
          onClick={() => onOpenCard(child.id)}
        >
          {child.title}
        </button>
      );
    }
  });

  const boundaryPoint = t.pointAt(boundaryArc);
  const campPoint = t.pointAt(campArc);

  return (
    <div className="atlas-trail atlas-trail--down" ref={colRef}>
      <svg className={svgClassName} viewBox={`0 0 ${width} ${contentHeight}`} preserveAspectRatio="none">
        <g className="atlas-trail__paths">
          {segments.map(({ child, start, end }, i) => {
            const group = statusGroupOf(child);
            const faded = group === "todo";
            const cuts = [{ at: end, radius: WAYPOINT_GAP_PX }];
            if (i > 0) cuts.push({ at: start, radius: WAYPOINT_GAP_PX });
            // Cut a gap at the campfire's position on EVERY segment when
            // parked (not just the frozen in-progress child's own segment)
            // — trimSegmentForMarkers is a no-op wherever the cut doesn't
            // overlap a given segment, so this also correctly covers the
            // zero-done/zero-in-progress fallback (campArc === boundaryX,
            // which can land on any segment, or before all of them).
            if (parked) cuts.push({ at: campArc, radius: CAMPFIRE_GAP_PX });
            return trimSegmentForMarkers(start, end, cuts).map(([a, b], j) => (
              <path
                key={`${child.id}-${j}`}
                className={"atlas-trail__path" + (faded ? " atlas-trail__path--faded" : "")}
                d={t.d(a, b)}
              />
            ));
          })}
        </g>

        <g
          className="atlas-trail__trailhead"
          transform={`translate(${t.pointAt(TRAILHEAD_RESERVE_PX).x - TRAILHEAD_ICON_SIZE_PX / 2}, 0)`}
        >
          <image
            href={trailheadIcon}
            x={0}
            y={0}
            width={TRAILHEAD_ICON_SIZE_PX}
            height={TRAILHEAD_ICON_SIZE_PX}
          />
          <title>where the saga began</title>
        </g>

        <g className="atlas-trail__markers">{svgMarkers}</g>

        {marching && (
          <g className="atlas-trail__party">
            <circle cx={boundaryPoint.x} cy={boundaryPoint.y} r={12} />
            <text x={boundaryPoint.x} y={boundaryPoint.y + 4} textAnchor="middle">
              ⚔
            </text>
            <title>{`the party — ${rollup.done}/${rollup.total} quests cleared`}</title>
          </g>
        )}

        {parked && (
          <g className="atlas-trail__camped">
            <image
              className="atlas-trail__campfire"
              href={campfireIcon}
              x={campPoint.x - MARKER_SIZE_PX - 4}
              y={campPoint.y - MARKER_SIZE_PX / 2}
              width={MARKER_SIZE_PX}
              height={MARKER_SIZE_PX}
            />
            <text className="atlas-trail__camped-label" x={campPoint.x + 8} y={campPoint.y + 5}>
              camped — on hold
            </text>
          </g>
        )}

        <g
          className={
            "atlas-trail__beast " +
            (slain ? "atlas-trail__beast--slain" : "atlas-trail__beast--alive") +
            ` atlas-trail__beast--hue-${beast.hueVariant}`
          }
          transform={`translate(${beastX}, ${beastY})`}
        >
          <BeastFace
            hue={slain ? "var(--qb-atlas-beast-slain)" : "var(--qb-atlas-beast-alive)"}
            horns={beast.horns}
            slain={slain}
          />
          <title>
            {slain
              ? `${beast.name} — vanquished!`
              : `${beast.name} awaits (${rollup.total - rollup.done} quests stand between)`}
          </title>
        </g>

        {slain && (
          <text className="atlas-trail__gold" x={beastX + 54} y={beastY + 30}>
            +{formatTokens(rollup.actual)} gold
          </text>
        )}
      </svg>

      {overlayTags.length > 0 && <div className="atlas-trail__overlays">{overlayTags}</div>}
    </div>
  );
}

export default AtlasTrailVertical;
