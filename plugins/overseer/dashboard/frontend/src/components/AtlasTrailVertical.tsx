import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { BoardCard, Rollup } from "../api/types";
import { formatDateStamp, parseCalendarDate, seedFor, wobblePathVertical } from "../board/atlasGeometry";
import {
  BEAST_RESERVE_PX,
  CAMPFIRE_GAP_PX,
  TRAILHEAD_RESERVE_PX,
  WAYPOINT_GAP_PX,
  beastAnchorX,
  boundaryX,
  campfireX,
  computeSegments,
  frozenSegment,
  openDependencies,
  orderChildrenForTrail,
  statusGroupOf,
  totalWeight,
  trailEndX,
  trimSegmentForMarkers,
  weightOf,
} from "../board/atlasTrailLayout";
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

/** Mobile Down orientation (HANDOFF): each epic is a column, the trail
 * marches top -> bottom on a FLAT per-complexity scale — deliberately NOT
 * the shared-across-rows `pxPerWeight` Across mode uses (HANDOFF: "no
 * fit-to-container — the page scrolls; same weight = same length across
 * columns" — flat already gives that property, no cross-column
 * measurement needed). This is why AtlasTrailVertical takes no
 * `pxPerWeight`/`laneWidth` props the way AtlasTrail does: every column is
 * geometrically independent. */
const V_PX_PER_WEIGHT = 72;

const DEFAULT_COLUMN_WIDTH = 280;
const MARKER_SIZE_PX = 20;
const NAME_TAG_TIER_OFFSET_PX = 16;

function weightLabel(child: BoardCard): string {
  return "★".repeat(weightOf(child));
}

/**
 * Down-mode's mirror of `AtlasTrail.tsx` — same per-status marker language
 * (done ✓, abandoned skull, AT HAND ring+pennant, faded todo + name-tags,
 * blocked boulder, campfire, party token, trailhead, beast), rotated onto a
 * vertical axis via `wobblePathVertical`. Kept as its own component rather
 * than an orientation branch inside AtlasTrail — the two scales (shared vs.
 * flat) and axes are different enough that folding them into one component
 * would trade a little duplication for a lot of conditional plumbing.
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
  const segments = computeSegments(ordered, V_PX_PER_WEIGHT);
  const epicTotalWeight = totalWeight(childCards);
  const trailEnd = trailEndX(epicTotalWeight, V_PX_PER_WEIGHT);
  const boundary = boundaryX(segments);
  const frozen = frozenSegment(segments);
  const campY = campfireX(segments);
  const contentHeight = trailEnd + BEAST_RESERVE_PX;

  const slain = card.status === "done";
  const parked = !slain && card.status === "parked";
  const marching = card.status === "in-flight";

  const t = wobblePathVertical(0, Math.max(contentHeight, 1), Math.max(width, 1), seed);

  const beastYRaw = beastAnchorX(trailEnd);
  const beastX = t.xAt(beastYRaw) - 24;

  const svgClassName = "atlas-trail__svg" + (accentKey ? ` atlas-trail__svg--accent-${accentKey}` : "");

  const svgMarkers: ReactNode[] = [];
  const overlayTags: ReactNode[] = [];
  let todoTier = 0;

  for (const { child, end } of segments) {
    const group = statusGroupOf(child);
    const my = end;
    const mx = t.xAt(end);
    const cleared = formatDateStamp(parseCalendarDate(child.updated));

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
            style={{ left: `${mx + 16}px`, top: `${my}px`, transform: "translateY(-50%)" }}
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
      overlayTags.push(
        <span
          key={`${child.id}-tag`}
          className={
            "trail-tag trail-tag--todo trail-tag--down " + (tier ? "trail-tag--tier-1" : "trail-tag--tier-0")
          }
          style={{ left: `${mx + 16 + tier * NAME_TAG_TIER_OFFSET_PX}px`, top: `${my}px`, transform: "translateY(-50%)" }}
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
            if (parked && frozen && child === frozen.child) {
              cuts.push({ at: campY, radius: CAMPFIRE_GAP_PX });
            }
            return trimSegmentForMarkers(start, end, cuts).map(([a, b], j) => (
              <path
                key={`${child.id}-${j}`}
                className={"atlas-trail__path" + (faded ? " atlas-trail__path--faded" : "")}
                d={wobblePathVertical(a, b, width, seed).d}
              />
            ));
          })}
        </g>

        <g
          className="atlas-trail__trailhead"
          transform={`translate(${t.xAt(TRAILHEAD_RESERVE_PX) - 9}, 0) scale(0.85)`}
        >
          <image href={trailheadIcon} x={0} y={0} width={MARKER_SIZE_PX} height={MARKER_SIZE_PX} />
          <title>where the saga began</title>
        </g>

        <g className="atlas-trail__markers">{svgMarkers}</g>

        {marching && (
          <g className="atlas-trail__party">
            <circle cx={t.xAt(boundary)} cy={boundary} r={12} />
            <text x={t.xAt(boundary)} y={boundary + 4} textAnchor="middle">
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
              x={t.xAt(campY) - MARKER_SIZE_PX - 4}
              y={campY - MARKER_SIZE_PX / 2}
              width={MARKER_SIZE_PX}
              height={MARKER_SIZE_PX}
            />
            <text className="atlas-trail__camped-label" x={t.xAt(campY) + 8} y={campY + 5}>
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
