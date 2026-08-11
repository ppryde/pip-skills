import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { BoardCard, Rollup } from "../api/types";
import { formatDateStamp, parseCalendarDate, seedFor } from "../board/atlasGeometry";
import {
  BEAST_ICON_SIZE_PX,
  BEAST_RESERVE_PX,
  CAMPFIRE_GAP_PX,
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
import { V_PX_PER_UNIT_SERPENTINE, serpentineTrail } from "../board/serpentineTrail";
import { beastFor } from "../board/beastName";
import { formatTokens } from "../board/formatTokens";
import BeastFace from "./BeastFace";

import trailheadIcon from "../assets/trail-icons/walled-village.svg";
import boulderIcon from "../assets/trail-icons/boulder.svg";
import campfireIcon from "../assets/trail-icons/campfire.png";
import abandonedIcon from "../assets/lane-icons/abandoned.png";

export interface AtlasTrailVerticalProps {
  card: BoardCard;
  rollup: Rollup;
  childCards: BoardCard[];
  cardsById: Map<string, BoardCard>;
  showNames: boolean;
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
 * 2026-08-11) rather than a flat straight drop — see `serpentineTrail.ts`
 * for the curve geometry and why "same weight = same length" holds in
 * path-arc terms there. `atlasTrailLayout.ts`'s scalar functions
 * (computeSegments/boundaryX/campfireX/trailEndX/beastAnchorX/
 * trimSegmentForMarkers) are reused UNCHANGED — they operate on a generic
 * "distance along the trail" scalar that's now a Y coordinate instead of
 * an X one, fed `V_PX_PER_UNIT_SERPENTINE` instead of Across mode's shared
 * `pxPerWeight`; only the FINAL (x,y) screen position (via
 * `serpentineTrail(width, seed).pointAt`) differs from Across mode's
 * straight `wobblePath`.
 *
 * Kept as its own component rather than an orientation branch inside
 * AtlasTrail — the two scales (shared vs. flat-per-column) and axes are
 * different enough that folding them into one component would trade a
 * little duplication for a lot of conditional plumbing.
 */
function AtlasTrailVertical({ card, rollup, childCards, cardsById, showNames, accentKey }: AtlasTrailVerticalProps) {
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
  const segments = computeSegments(ordered, V_PX_PER_UNIT_SERPENTINE);
  const epicTotalWeight = totalWeight(childCards);
  const trailEnd = trailEndX(epicTotalWeight, V_PX_PER_UNIT_SERPENTINE);
  const boundary = boundaryX(segments);
  const campY = campfireX(segments);
  const contentHeight = trailEnd + BEAST_RESERVE_PX;

  const slain = card.status === "done";
  const parked = !slain && card.status === "parked";
  const marching = card.status === "in-flight";

  const t = serpentineTrail(Math.max(width, 1), seed);

  const beastYRaw = beastAnchorX(trailEnd);
  const beastPoint = t.pointAt(beastYRaw);
  const beastX = beastPoint.x - BEAST_ICON_SIZE_PX / 2;

  const svgClassName = "atlas-trail__svg" + (accentKey ? ` atlas-trail__svg--accent-${accentKey}` : "");

  // "Flipping to whichever side has room on the current sweep" (HANDOFF) —
  // a point on the left half of the column has more room to its right
  // (before the sweep's own left turn-back), and vice versa.
  function roomySide(x: number): "left" | "right" {
    return x < width / 2 ? "right" : "left";
  }

  const svgMarkers: ReactNode[] = [];
  const overlayTags: ReactNode[] = [];
  let todoTier = 0;

  for (const { child, end } of segments) {
    const group = statusGroupOf(child);
    const my = end;
    const { x: mx } = t.pointAt(end);
    const cleared = formatDateStamp(parseCalendarDate(child.updated));
    const side = roomySide(mx);
    const tagStyle = {
      [side]: side === "right" ? `${width - mx + 16}px` : `${mx + 16}px`,
      top: `${my}px`,
      transform: "translateY(-50%)",
    } as const;

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
      continue;
    }

    if (group === "in-progress") {
      const atHand = !parked;
      svgMarkers.push(
        <g key={child.id} className="atlas-trail__waypoint atlas-trail__waypoint--athand">
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
      if (atHand) {
        overlayTags.push(
          <span
            key={`${child.id}-pennant`}
            className="trail-tag atlas-trail__pennant--athand trail-tag--down"
            style={tagStyle}
          >
            ◆ AT HAND
          </span>
        );
      }
      continue;
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

    if (showNames) {
      const tierTagStyle = {
        ...tagStyle,
        [side]:
          side === "right"
            ? `${width - mx + 16 + tier * NAME_TAG_TIER_OFFSET_PX}px`
            : `${mx + 16 + tier * NAME_TAG_TIER_OFFSET_PX}px`,
      };
      overlayTags.push(
        <span
          key={`${child.id}-tag`}
          className={
            "trail-tag trail-tag--todo trail-tag--down " + (tier ? "trail-tag--tier-1" : "trail-tag--tier-0")
          }
          style={tierTagStyle}
          title={`${child.title} · ${weightLabel(child)}`}
        >
          {child.title}
        </span>
      );
    }
  }

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
            // zero-done/zero-in-progress fallback (campY === boundaryX,
            // which can land on any segment, or before all of them).
            if (parked) cuts.push({ at: campY, radius: CAMPFIRE_GAP_PX });
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
          transform={`translate(${t.pointAt(TRAILHEAD_RESERVE_PX).x - 9}, 0) scale(0.85)`}
        >
          <image href={trailheadIcon} x={0} y={0} width={MARKER_SIZE_PX} height={MARKER_SIZE_PX} />
          <title>where the saga began</title>
        </g>

        <g className="atlas-trail__markers">{svgMarkers}</g>

        {marching && (
          <g className="atlas-trail__party">
            <circle cx={t.pointAt(boundary).x} cy={boundary} r={12} />
            <text x={t.pointAt(boundary).x} y={boundary + 4} textAnchor="middle">
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
              x={t.pointAt(campY).x - MARKER_SIZE_PX - 4}
              y={campY - MARKER_SIZE_PX / 2}
              width={MARKER_SIZE_PX}
              height={MARKER_SIZE_PX}
            />
            <text className="atlas-trail__camped-label" x={t.pointAt(campY).x + 8} y={campY + 5}>
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
          transform={`translate(${beastX}, ${beastYRaw})`}
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
          <text className="atlas-trail__gold" x={beastX + 54} y={beastYRaw + 30}>
            +{formatTokens(rollup.actual)} gold
          </text>
        )}
      </svg>

      {overlayTags.length > 0 && <div className="atlas-trail__overlays">{overlayTags}</div>}
    </div>
  );
}

export default AtlasTrailVertical;
