import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { BoardCard, Rollup } from "../api/types";
import { formatDateStamp, parseCalendarDate, seedFor, wobblePath } from "../board/atlasGeometry";
import {
  BEAST_ICON_SIZE_PX,
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
import { beastFor } from "../board/beastName";
import { formatTokens } from "../board/formatTokens";
import BeastFace from "./BeastFace";

import trailheadIcon from "../assets/trail-icons/walled-village.svg";
import boulderIcon from "../assets/trail-icons/boulder.svg";
import campfireIcon from "../assets/trail-icons/campfire.png";
import abandonedIcon from "../assets/lane-icons/abandoned.png";

export interface AtlasTrailProps {
  card: BoardCard;
  /** Non-null by construction — same contract as AtlasRailCard's `rollup`. */
  rollup: Rollup;
  /** The epic's own child cards — named to avoid colliding with React's
   * implicit `children` prop, same rationale as AtlasRailCard's. */
  childCards: BoardCard[];
  /** Every card on the board, keyed by id — needed to resolve a child's
   * `depends_on` targets for the blocked-boulder overlay (a dependency can
   * point outside the epic's own children). */
  cardsById: Map<string, BoardCard>;
  /** The ONE shared px-per-weight scalar (EpicAtlas's `globalPxPerWeight`,
   * recomputed each render across every visible epic) — NOT re-derived per
   * lane, that's what makes cross-row length comparisons real. */
  pxPerWeight: number;
  /** The shared lane width (EpicAtlas measures this ONCE, off any lane —
   * every lane renders at the same CSS width). Drives the SVG viewBox
   * width; this component only self-measures its own HEIGHT (see the
   * ResizeObserver effect below) — "only the width scale is shared". */
  laneWidth: number;
  /** Quest-names toolbar toggle (HANDOFF, default on) — hides the todo
   * name-tags only; tooltips and the AT HAND pennant are unaffected. */
  showNames: boolean;
  /** Lane-computed guild accent key — stable class hook only; colour
   * resolution is the later styling chunk's job (see BeastFace's
   * `--qb-beast-ink` precedent). */
  accentKey?: string;
}

/** Default lane height mirrors the design reference's `min-height: 104px`
 * lane — used until the first real ResizeObserver measurement lands. */
const DEFAULT_LANE_HEIGHT = 104;

const MARKER_SIZE_PX = 20;
const NAME_TAG_TIER_OFFSET_PX = 16;
const NAME_TAG_TILT_DEG = 1.5;

function weightLabel(child: BoardCard): string {
  return "★".repeat(weightOf(child));
}

function AtlasTrail({
  card,
  rollup,
  childCards,
  cardsById,
  pxPerWeight,
  laneWidth,
  showNames,
  accentKey,
}: AtlasTrailProps) {
  const laneRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(DEFAULT_LANE_HEIGHT);

  // Re-measures whenever the lane's own box HEIGHT changes — including when
  // the sibling rail card expands/collapses its sub-quest list and grows
  // the row. Width is deliberately NOT re-measured here (HANDOFF: "sample
  // each lane's own height for its SVG viewBox — only the width scale is
  // shared") — it comes from the `laneWidth` prop, one shared measurement
  // EpicAtlas makes for every row, so a per-lane remeasurement can never
  // desync a row's pxPerWeight from what EpicAtlas actually used to compute it.
  useEffect(() => {
    const el = laneRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const measured = entry.contentRect.height;
      setHeight(Number.isFinite(measured) ? measured : DEFAULT_LANE_HEIGHT);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const laneHeight = height || DEFAULT_LANE_HEIGHT;
  const width = Number.isFinite(laneWidth) && laneWidth > 0 ? laneWidth : 0;
  const seed = seedFor(card.id);
  const beast = beastFor(card.id);

  const ordered = orderChildrenForTrail(childCards);
  const segments = computeSegments(ordered, pxPerWeight);
  const epicTotalWeight = totalWeight(childCards);
  const trailEnd = trailEndX(epicTotalWeight, pxPerWeight);
  const boundary = boundaryX(segments);
  const campX = campfireX(segments);

  const slain = card.status === "done";
  const parked = !slain && card.status === "parked";
  // "Marching" — the only state with a live party token — mirrors the
  // prototype's `ep.status === "in-flight"` branch exactly; a planned/
  // blocked epic has no party token either (nothing marches until real
  // work starts), only the trailhead + beast still render for it.
  const marching = card.status === "in-flight";

  const t = wobblePath(0, Math.max(width, 1), laneHeight, seed);

  // Impl-review round 1, finding 1: the draw-x clamp and the y-SAMPLE-x used
  // to be two different ad-hoc numbers (`width - 52` vs `width - 30`), which
  // (a) pulled the heaviest epic's beast off the HANDOFF anchor formula and
  // (b) sampled the wobble line's y at a DIFFERENT x than where the beast
  // actually gets drawn, floating it off the line. ONE clamp, derived from
  // BEAST_ICON_SIZE_PX (the beast's own rendered width), used for both the
  // draw position and the y-sample now — by construction of
  // laneUsableWidth/globalPxPerWeight/BEAST_RESERVE_PX, the heaviest epic's
  // un-clamped beastXRaw already lands at exactly `width - BEAST_ICON_SIZE_PX`,
  // so this clamp is a defensive floor, not the normal path.
  const beastXRaw = beastAnchorX(trailEnd);
  const beastXClamped = Math.min(beastXRaw, width - BEAST_ICON_SIZE_PX);
  const beastY = t.yAt(beastXClamped) - BEAST_ICON_SIZE_PX / 2;

  const svgClassName =
    "atlas-trail__svg" + (accentKey ? ` atlas-trail__svg--accent-${accentKey}` : "");

  // Built imperatively (rather than three separate JSX .map passes) because
  // the AT-HAND pennant and the todo name-tags are plain positioned HTML
  // (matching the prototype's own technique: absolutely-positioned `<div>`
  // tags layered OVER the SVG, not squeezed into it via <foreignObject>) —
  // one loop over `segments` builds the SVG marker for each child AND its
  // optional HTML overlay tag together, so the two never drift out of sync
  // with each other's per-child `tier`/position math.
  const svgMarkers: ReactNode[] = [];
  const overlayTags: ReactNode[] = [];
  let todoTier = 0;

  segments.forEach(({ child, end }, segmentIndex) => {
    const isLastChild = segmentIndex === segments.length - 1;
    const group = statusGroupOf(child);
    const mx = end;
    const my = t.yAt(end);
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
      return;
    }

    if (group === "in-progress") {
      // Suppressed on a parked epic — a camped party has no quest "at
      // hand" (HANDOFF); the marker still renders, just without the
      // pulsing ring or the pennant.
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
      // The AT HAND pennant is a status marker, not a name-tag — it always
      // shows on a marching epic's quest at hand, regardless of the
      // names toggle (HANDOFF).
      if (atHand) {
        overlayTags.push(
          <span
            key={`${child.id}-pennant`}
            className="trail-tag atlas-trail__pennant--athand"
            style={{ left: `${mx}px`, top: `${my - 16}px`, transform: "translate(-50%, -100%)" }}
          >
            ◆ AT HAND
          </span>
        );
      }
      return;
    }

    // "todo" — the ahead trail: real, faded, at-weight named quests. A
    // BLOCKED quest (open depends_on) draws the barrier doodle instead of
    // the plain waypoint dot; still ahead ground, still gets a name-tag.
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
            ? `${child.title} — the way is barred · ${
                cardsById.get(openDeps[0])?.title ?? "blocked"
              }`
            : `${child.title} — ahead · ${weightLabel(child)}`}
        </title>
      </g>
    );

    // Impl-review round 2, finding 5: the trail's LAST child's marker sits
    // exactly at the trail's true end by construction (its segment's own
    // `end` IS `trailEnd`) — only BEAST_ANCHOR_OFFSET_PX(26px) away from
    // the beast's own left edge, guaranteed on every trail regardless of
    // length. A centred name-tag there routinely crowds/overlaps the
    // beast doodle, so it's suppressed rather than shifted — the marker
    // itself and its full-name+weight tooltip still work fine without the
    // on-trail label. Deliberately keyed on "is this literally the last
    // child" (not a distance-from-beast estimate): an early prototype of
    // this fix used a conservative `TAG_HALF_WIDTH_PX` distance check
    // instead, which over-suppressed EVERY tag on a short/low-weight
    // trail (any marker within roughly the tag's own generous max-width
    // of the beast), not just the genuinely-adjacent last one.
    if (showNames && !isLastChild) {
      overlayTags.push(
        <span
          key={`${child.id}-tag`}
          className={"trail-tag trail-tag--todo " + (tier ? "trail-tag--tier-1" : "trail-tag--tier-0")}
          style={{
            left: `${mx}px`,
            top: `${my - 11 - tier * NAME_TAG_TIER_OFFSET_PX}px`,
            transform: `translate(-50%, -100%) rotate(${
              tier ? NAME_TAG_TILT_DEG : -NAME_TAG_TILT_DEG
            }deg)`,
          }}
          title={`${child.title} · ${weightLabel(child)}`}
        >
          {child.title}
        </span>
      );
    }
  });

  return (
    <div className="atlas-trail" ref={laneRef}>
      <svg
        className={svgClassName}
        viewBox={`0 0 ${width} ${laneHeight}`}
        preserveAspectRatio="none"
      >
        <g className="atlas-trail__paths">
          {segments.map(({ child, start, end }, i) => {
            const group = statusGroupOf(child);
            const faded = group === "todo";
            const cuts = [{ at: end, radius: WAYPOINT_GAP_PX }];
            if (i > 0) cuts.push({ at: start, radius: WAYPOINT_GAP_PX });
            // Impl-review round 1, finding 3: cutting the campfire gap ONLY
            // on the frozen in-progress child's own segment missed the
            // fallback case (a parked epic with zero done AND zero
            // in-progress children — campfireX falls all the way back to
            // boundaryX, which can land on ANY segment, or before all of
            // them). Cutting at campX on every segment unconditionally is
            // safe — trimSegmentForMarkers is a no-op wherever campX falls
            // outside a given segment's own range, so this never trims
            // ground the campfire doesn't actually sit on.
            if (parked) cuts.push({ at: campX, radius: CAMPFIRE_GAP_PX });
            return trimSegmentForMarkers(start, end, cuts).map(([a, b], j) => (
              <path
                key={`${child.id}-${j}`}
                className={"atlas-trail__path" + (faded ? " atlas-trail__path--faded" : "")}
                d={wobblePath(a, b, laneHeight, seed).d}
              />
            ));
          })}
        </g>

        <g
          className="atlas-trail__trailhead"
          transform={`translate(0, ${t.yAt(TRAILHEAD_RESERVE_PX) - 9}) scale(0.85)`}
        >
          <image href={trailheadIcon} x={0} y={0} width={MARKER_SIZE_PX} height={MARKER_SIZE_PX} />
          <title>where the saga began</title>
        </g>

        <g className="atlas-trail__markers">{svgMarkers}</g>

        {marching && (
          <g className="atlas-trail__party">
            <circle cx={boundary} cy={t.yAt(boundary) - 18} r={12} />
            <text x={boundary} y={t.yAt(boundary) - 13} textAnchor="middle">
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
              x={campX - MARKER_SIZE_PX / 2}
              y={t.yAt(campX) - MARKER_SIZE_PX - 4}
              width={MARKER_SIZE_PX}
              height={MARKER_SIZE_PX}
            />
            <text className="atlas-trail__camped-label" x={campX + 14} y={t.yAt(campX) - 8}>
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
          transform={`translate(${beastXClamped}, ${beastY})`}
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
          <text className="atlas-trail__gold" x={beastXClamped + 54} y={beastY + 30}>
            +{formatTokens(rollup.actual)} gold
          </text>
        )}
      </svg>

      {overlayTags.length > 0 && <div className="atlas-trail__overlays">{overlayTags}</div>}
    </div>
  );
}

export default AtlasTrail;
