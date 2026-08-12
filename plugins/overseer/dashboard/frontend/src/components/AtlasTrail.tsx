import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { BoardCard, Rollup } from "../api/types";
import { formatDateStamp, parseCalendarDate, seedFor, wobblePath } from "../board/atlasGeometry";
import {
  BEAST_ICON_SIZE_PX,
  CAMPFIRE_GAP_PX,
  TRAILHEAD_ICON_SIZE_PX,
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
import { rarityStars } from "../board/rarityStars";
import { randomMonsterIcon } from "../board/monsterIcons";
import { StarIcon } from "./icons";

import trailheadIcon from "../assets/villages/icon_7.png";
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
  /** The shared SVG content width (EpicAtlas computes this ONCE, from the
   * HEAVIEST visible epic's own trailEnd + beast reserve on the shared
   * `pxPerWeight` scale — every lane renders its SVG at this same width,
   * deliberately NOT the lane's own (viewport-constrained) box width, so a
   * cramped board overspills+scrolls instead of compressing further; see
   * `MIN_PX_PER_WEIGHT`'s doc comment in atlasTrailLayout.ts). Drives the
   * SVG's own width/viewBox-width and the beast-x clamp; this component
   * only self-measures its own HEIGHT (see the ResizeObserver effect
   * below) — "only the width scale is shared". */
  trailWidth: number;
  /** Quest-names toolbar toggle (HANDOFF, default on) — hides the todo/done
   * name-tags only; tooltips and the AT HAND pennant are unaffected. */
  showNames: boolean;
  /** Opens the existing card detail drawer for a clicked trail name-tag
   * (todo or done) — same drawer AtlasRailCard's own click already opens,
   * reused rather than a new modal (HANDOFF chunk 5 precedent). */
  onOpenCard: (id: string) => void;
  /** Mobile across-view POC: the currently-previewed CHILD id (or null). When
   * it matches one of this trail's own children, a preview card floats above
   * that child's marker, high enough to clear the trail's name-tags. Desktop /
   * down-mode pass null (EpicAtlas gates it) so nothing renders. */
  previewChildId?: string | null;
  /** Opens the REAL card-detail drawer (sidebar) — used by the preview's
   * body-click; distinct from `onOpenCard`, which on mobile-across is the
   * toggle that opens/closes the popup itself. */
  onOpenDrawer?: (id: string) => void;
  /** Lane-computed guild accent key — stable class hook only; colour
   * resolution is the later styling chunk's job (see BeastFace's
   * `--qb-beast-ink` precedent). */
  accentKey?: string;
}

/** Default lane height — used until the first real ResizeObserver
 * measurement lands. Bumped from the design reference's original 104px
 * (Task 2): the across-mode trail's name-tags now alternate above AND
 * below the path, so the floor needs to clear a below tag's own box under a
 * max-amplitude wobble crest without crowding the row's bottom divider.
 * Mirrors `.atlas-chart__lane`'s own `min-height` in styles.css. */
const DEFAULT_LANE_HEIGHT = 112;

const MARKER_SIZE_PX = 20;
/** Vertical clearance between a marker and its name-tag's near edge — same
 * magnitude used on both banks of the Task 2 alternation (`my - GAP` for an
 * above tag's bottom-anchored edge, `my + GAP` for a below tag's top-anchored
 * one), so the zig-zag sits symmetric on either side of the path. */
const NAME_TAG_GAP_PX = 11;
const NAME_TAG_TILT_DEG = 1.5;

function weightLabel(child: BoardCard): string {
  return "★".repeat(weightOf(child));
}

/** Places a trail name-tag on one of the two alternating banks of the path
 * (Task 2 — "signposts on both banks"). ABOVE is the original placement:
 * bottom-anchored (`translate(-50%, -100%)`) with a small negative tilt.
 * BELOW mirrors it top-anchored (`translate(-50%, 0)`) with the opposite
 * tilt, so a tag hangs down from the path rather than sitting on it. Which
 * bank a given tag lands on is the caller's call (one running counter
 * shared across the todo AND done groups — see `tagIndex` below), not this
 * function's. */
function nameTagStyle(mx: number, my: number, below: boolean): CSSProperties {
  return below
    ? {
        left: `${mx}px`,
        top: `${my + NAME_TAG_GAP_PX}px`,
        transform: `translate(-50%, 0) rotate(${NAME_TAG_TILT_DEG}deg)`,
      }
    : {
        left: `${mx}px`,
        top: `${my - NAME_TAG_GAP_PX}px`,
        transform: `translate(-50%, -100%) rotate(${-NAME_TAG_TILT_DEG}deg)`,
      };
}

function AtlasTrail({
  card,
  rollup,
  childCards,
  cardsById,
  pxPerWeight,
  trailWidth,
  showNames,
  onOpenCard,
  previewChildId,
  onOpenDrawer,
  accentKey,
}: AtlasTrailProps) {
  const laneRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(DEFAULT_LANE_HEIGHT);
  // Boss art (POC): one random monster per mount — new on a fresh page load,
  // but stable across this epic's re-renders so it doesn't flicker.
  const monster = useMemo(() => randomMonsterIcon(), []);

  // Re-measures whenever the lane's own box HEIGHT changes — including when
  // the sibling rail card expands/collapses its sub-quest list and grows
  // the row. Width is deliberately NOT re-measured here (HANDOFF: "sample
  // each lane's own height for its SVG viewBox — only the width scale is
  // shared") — it comes from the `trailWidth` prop, one shared measurement
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
  const width = Number.isFinite(trailWidth) && trailWidth > 0 ? trailWidth : 0;
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
  // laneUsableWidth/globalPxPerWeight/BEAST_RESERVE_PX (now folded into
  // EpicAtlas's shared `trailWidth`), the heaviest epic's un-clamped
  // beastXRaw already lands at exactly `width - BEAST_ICON_SIZE_PX`, so this
  // clamp is a defensive floor, not the normal path.
  const beastXRaw = beastAnchorX(trailEnd);
  const beastXClamped = Math.min(beastXRaw, width - BEAST_ICON_SIZE_PX);
  const beastY = t.yAt(beastXClamped) - BEAST_ICON_SIZE_PX / 2;

  // `--across` renders the SVG at its OWN intrinsic pixel size (the
  // `width`/`height` attributes below), never stretched/squeezed to fill
  // its parent `.atlas-trail` box (which stays lane-width-sized) — that's
  // what lets a wide trail overflow the lane instead of being compressed
  // back into it (Feature 1 / MIN_PX_PER_WEIGHT; see styles.css). Mirrors
  // AtlasTrailVertical's own `height: auto` trick for the opposite axis.
  const svgClassName =
    "atlas-trail__svg atlas-trail__svg--across" +
    (accentKey ? ` atlas-trail__svg--accent-${accentKey}` : "");

  // Built imperatively (rather than three separate JSX .map passes) because
  // the AT-HAND pennant and the todo name-tags are plain positioned HTML
  // (matching the prototype's own technique: absolutely-positioned `<div>`
  // tags layered OVER the SVG, not squeezed into it via <foreignObject>) —
  // one loop over `segments` builds the SVG marker for each child AND its
  // optional HTML overlay tag together, so the two never drift out of sync
  // with each other's per-child placement math.
  const svgMarkers: ReactNode[] = [];
  const overlayTags: ReactNode[] = [];
  // Task 2: ONE running counter across every RENDERED name-tag — both the
  // todo group and the done group (Feature 3) — in trail order, so the
  // above/below alternation zig-zags consistently along the whole trail
  // rather than resetting (or colliding) where a done stretch hands off to
  // a todo one. Only increments where a tag actually renders (inside each
  // `showNames && !isLastChild` check below) — a suppressed last-child tag
  // never consumes a slot in the alternation. Replaces the old two
  // independent `todoTier`/`doneTier` counters, which only ever stacked
  // tags ABOVE the path.
  let tagIndex = 0;

  // Mobile across-view POC: capture the tapped child's x during the marker
  // loop so the preview floats over the exact node. Holder object (not a bare
  // `let`) so TS keeps its `{...} | null` type after the loop — it can't see
  // the assignment inside the forEach callback.
  const previewAnchor: { value: { mx: number; child: BoardCard } | null } = {
    value: null,
  };

  segments.forEach(({ child, end }) => {
    const group = statusGroupOf(child);
    const mx = end;
    const my = t.yAt(end);
    const cleared = formatDateStamp(parseCalendarDate(child.updated));
    if (previewChildId && child.id === previewChildId) {
      previewAnchor.value = { mx, child };
    }

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
      // Feature 3: a greyed name-tag for a done (or abandoned) child too —
      // same overlay-tag mechanism, same tier-alternation/tilt pattern, and
      // the same last-child beast-clearance suppression as the todo tag
      // below (a done child CAN be the trail's last child — an
      // all-done/no-todo epic, or an all-done epic with nothing after).
      if (showNames) {
        const below = tagIndex % 2 === 1;
        tagIndex++;
        overlayTags.push(
          <button
            type="button"
            key={`${child.id}-tag`}
            className={"trail-tag trail-tag--done" + (below ? " trail-tag--below" : "")}
            style={nameTagStyle(mx, my, below)}
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
      // Suppressed on a parked epic — a camped party has no quest "at
      // hand" (HANDOFF); the marker still renders, just without the
      // pulsing ring or the pennant.
      const atHand = !parked;
      svgMarkers.push(
        <g
          key={child.id}
          className="atlas-trail__waypoint atlas-trail__waypoint--athand"
          // The pennant (below) is suppressed on the trail's last child —
          // when that happens, this marker is the ONLY AT HAND affordance,
          // so it opens the same card detail drawer directly (see the
          // `.atlas-trail__waypoint--athand` cursor/hover rules in
          // styles.css). Only this in-progress marker gets a click handler
          // — the done/todo markers stay tooltip-only, their own name-tags
          // already cover the click affordance.
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
      // The AT HAND pennant is a status marker, not a name-tag — it always
      // shows on a marching epic's quest at hand, regardless of the
      // names toggle (HANDOFF), EXCEPT the same last-child beast-clearance
      // rule the todo name-tag gets below (round 3 closing item: the
      // pennant has the identical geometry exposure when the trail ENDS on
      // the in-progress child — done -> in-progress, zero todos after —
      // its marker sits exactly BEAST_ANCHOR_OFFSET_PX from the beast, same
      // as any other last child). Marker + tooltip still always render;
      // only the floating pennant label suppresses.
      if (atHand) {
        overlayTags.push(
          <button
            type="button"
            key={`${child.id}-pennant`}
            className="trail-tag atlas-trail__pennant--athand"
            style={{ left: `${mx}px`, top: `${my - 16}px`, transform: "translate(-50%, -100%)" }}
            onClick={() => onOpenCard(child.id)}
          >
            ◆ AT HAND
          </button>
        );
      }
      return;
    }

    // "todo" — the ahead trail: real, faded, at-weight named quests. A
    // BLOCKED quest (open depends_on) draws the barrier doodle instead of
    // the plain waypoint dot; still ahead ground, still gets a name-tag.
    const openDeps = openDependencies(child, cardsById);
    const blocked = openDeps.length > 0;

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

    // Every quest gets its on-trail name-tag, including the last one (which
    // sits right before the boss) — previously the last child's tag was
    // suppressed to avoid crowding the beast, but that hid one quest's label
    // on every journey ("one card short"), so it's shown now.
    if (showNames) {
      const below = tagIndex % 2 === 1;
      tagIndex++;
      overlayTags.push(
        <button
          type="button"
          key={`${child.id}-tag`}
          className={
            "trail-tag trail-tag--todo" +
            (blocked ? " trail-tag--blocked" : "") +
            (below ? " trail-tag--below" : "")
          }
          style={nameTagStyle(mx, my, below)}
          title={`${child.title} · ${weightLabel(child)}`}
          onClick={() => onOpenCard(child.id)}
        >
          {child.title}
        </button>
      );
    }
  });

  const preview = previewAnchor.value;
  const previewStars = preview ? rarityStars(preview.child.complexity) : 0;

  return (
    <div className="atlas-trail" ref={laneRef}>
      <svg
        className={svgClassName}
        width={width}
        height={laneHeight}
        viewBox={`0 0 ${width} ${laneHeight}`}
        preserveAspectRatio="none"
      >
        <g className="atlas-trail__paths">
          {segments.map(({ child, start, end }, i) => {
            const group = statusGroupOf(child);
            const faded = group === "todo";
            // Extend only the DRAWN path (never the weight math or waypoint
            // positions): the first segment reaches back under the trailhead
            // village and the last runs out under the monster boss, so the
            // trail visibly starts and ends beneath its bookend icons instead
            // of stopping short of them.
            const drawStart = i === 0 ? TRAILHEAD_ICON_SIZE_PX / 2 : start;
            const drawEnd =
              i === segments.length - 1
                ? beastXClamped + BEAST_ICON_SIZE_PX / 2
                : end;
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
            return trimSegmentForMarkers(drawStart, drawEnd, cuts).map(([a, b], j) => (
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
          // Anchor the village vertically to the path's ACTUAL start point
          // (yAt at the village's own centre-x, = the line's `drawStart`), not
          // yAt(TRAILHEAD_RESERVE_PX) — otherwise, wherever the wobble climbs or
          // dips between the two, the line's first point floats above/below the
          // village. Now the line always emerges from under the village.
          transform={`translate(0, ${
            t.yAt(TRAILHEAD_ICON_SIZE_PX / 2) - TRAILHEAD_ICON_SIZE_PX / 2 - 10
          })`}
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
          {/* Boss art (POC): a random monster icon, doubled to 128px and
              centred on the old 48px BeastFace anchor (offset -40 = -(128-48)/2)
              to absorb the art's own transparent margin. Faded when
              vanquished. */}
          <image
            href={monster}
            x={-40}
            y={-40}
            width={128}
            height={128}
            opacity={slain ? 0.5 : 1}
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

      {overlayTags.length > 0 && (
        <div className="atlas-trail__overlays">{overlayTags}</div>
      )}

      {/* Mobile across-view POC: a tapped child's preview, anchored to its
          marker's x (`left: mx`) but sitting at the TOP of the lane and lifted
          fully above it (CSS `top: 0` + translateY(-100%)) so it clears the
          name-tags. Rendered as a DIRECT child of `.atlas-trail` — NOT inside
          the overlay layer, whose own `z-index: 2` stacking context trapped it
          UNDER the sticky epic-card rail (z-index 3) — with a high z-index so
          it paints above that rail. Body-click opens the real drawer; the ✕
          toggles it closed. */}
      {preview && (
        <div
              className={
                "atlas-trail__preview atlas-trail__preview--" +
                statusGroupOf(preview.child)
              }
              style={{ left: `${preview.mx}px` }}
              role="button"
              tabIndex={0}
              onClick={() => onOpenDrawer?.(preview.child.id)}
            >
              <button
                type="button"
                className="atlas-trail__preview-close"
                aria-label="Close preview"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenCard(preview.child.id);
                }}
              >
                ✕
              </button>
              <div className="atlas-trail__preview-top">
                <span className="atlas-trail__preview-id">{preview.child.id}</span>
                {previewStars > 0 && (
                  <span className="atlas-trail__preview-stars" aria-hidden="true">
                    {[0, 1, 2, 3].map((s) => (
                      <StarIcon
                        key={s}
                        filled={s < previewStars}
                        className={
                          "atlas-trail__preview-star " +
                          (s < previewStars
                            ? "atlas-trail__preview-star--filled"
                            : "atlas-trail__preview-star--empty")
                        }
                      />
                    ))}
                  </span>
                )}
              </div>
              <div className="atlas-trail__preview-title">{preview.child.title}</div>
              <div className="atlas-trail__preview-status">
                {preview.child.status}
                {preview.child.stage ? ` · ${preview.child.stage}` : ""}
              </div>
              {preview.child.checklist.length > 0 && (
                <div className="atlas-trail__preview-checklist">
                  {
                    preview.child.checklist.filter(
                      (e) => e.status === "completed"
                    ).length
                  }
                  /{preview.child.checklist.length} done
                </div>
              )}
            </div>
          )}
    </div>
  );
}

export default AtlasTrail;
