import { useEffect, useRef, useState } from "react";
import type { BoardCard, Rollup } from "../api/types";
import {
  type AtlasWindow,
  formatDateStamp,
  parseCalendarDate,
  pctForDate,
  projectedEnd,
  seedFor,
  wobblePath,
} from "../board/atlasGeometry";
import { beastFor } from "../board/beastName";
import { formatTokens } from "../board/formatTokens";
import BeastFace from "./BeastFace";

export interface AtlasTrailProps {
  card: BoardCard;
  /** Non-null by construction — same contract as AtlasRailCard's `rollup`. */
  rollup: Rollup;
  /** The epic's own child cards — named to avoid colliding with React's
   * implicit `children` prop, same rationale as AtlasRailCard's. */
  childCards: BoardCard[];
  today: Date;
  /** The atlas's shared axis window (`computeWindow`). Named `dateWindow`
   * rather than `window` so it never shadows the DOM global of the same
   * name inside this component. */
  dateWindow: AtlasWindow;
  /** Lane-computed guild accent key — stable class hook only; colour
   * resolution is the later styling chunk's job (see BeastFace's
   * `--qb-beast-ink` precedent). */
  accentKey?: string;
}

interface LaneSize {
  width: number;
  height: number;
}

/** Default lane height mirrors the design reference's `min-height: 104px`
 * lane — used until the first real ResizeObserver measurement lands. */
const DEFAULT_LANE_HEIGHT = 104;

/** Fixed pixel clearance between a parked epic's camp (x1) and its waiting
 * beast — sized for the "camped — on hold" label's own rendered width
 * (`.atlas-trail__camped-label`, Patrick Hand ~13px, starts at x1+14), not
 * a fraction of the lane's width (which doesn't track the label's size at
 * all — a verification-round finding). */
const PARKED_BEAST_CLEARANCE_PX = 130;

function AtlasTrail({ card, rollup, childCards, today, dateWindow, accentKey }: AtlasTrailProps) {
  const laneRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<LaneSize>({ width: 0, height: DEFAULT_LANE_HEIGHT });

  // Re-measures whenever the lane's own box changes — including when the
  // sibling rail card expands/collapses its sub-quest list and grows the
  // row (HANDOFF: "The lane grows with its rail card ... and the trail
  // re-centres").
  useEffect(() => {
    const el = laneRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      // Defense-in-depth: a real browser never reports a non-finite
      // contentRect, but every x/y/cx/cy this component computes derives
      // from `width`/`height` directly (bypassing pctForDate's own NaN
      // guard entirely) — never let a pathological measurement into state.
      setSize({
        width: Number.isFinite(width) ? width : 0,
        height: Number.isFinite(height) ? height : DEFAULT_LANE_HEIGHT,
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { width, height } = size;
  const laneHeight = height || DEFAULT_LANE_HEIGHT;
  const seed = seedFor(card.id);
  const beast = beastFor(card.id);

  const doneChildren = childCards.filter((c) => c.status === "done");

  const createdDate = parseCalendarDate(card.created);
  const x0 = (pctForDate(createdDate, dateWindow) / 100) * width;

  // Walked trail end (HANDOFF's Data mapping): today while in-flight, the
  // epic's own `updated` once parked (last touched before pitching camp),
  // or its own `updated` once done (the epic mutator stamps `updated` at
  // completion, so this doubles as "last child updated" without needing
  // childCards to be non-empty). A `planned` epic (design ruling,
  // verification round 1) hasn't sent anyone out yet — there is no walked
  // ground, so its "walked end" is the camp itself (x1 === x0), and the
  // uncharted-ground branch below (which starts at x1) ends up starting
  // from the camp with no special-casing needed.
  const slain = card.status === "done";
  const parked = !slain && card.status === "parked";
  const planned = !slain && !parked && card.status === "planned";
  // "Marching" — the ONLY state with a live party token and a real walked
  // trail — is everything else (in-flight/blocked).
  const marching = !slain && !parked && !planned;
  const walkedEndDate = slain || parked ? parseCalendarDate(card.updated) : planned ? createdDate : today;
  const x1 = (pctForDate(walkedEndDate, dateWindow) / 100) * width;

  const walked = wobblePath(x0, x1, laneHeight, seed);

  let beastX = x1 + 26;
  let uncharted: ReturnType<typeof wobblePath> | null = null;

  if (parked) {
    // A camped party has no pace to project (HANDOFF: "Parked: no
    // projection") — the beast just waits past the camp, no faded
    // "uncharted ground" path drawn at all (that's in-flight only).
    // Verification-round finding: a PERCENTAGE-of-lane-width offset (the
    // former `width * 0.05`) doesn't track the "camped — on hold" label's
    // own rendered width at all, so at typical/wide lane widths the beast
    // sat close enough to visibly overlap the label. A fixed pixel
    // clearance does — it's sized for the label's own text regardless of
    // how wide the lane happens to be.
    beastX = x1 + PARKED_BEAST_CLEARANCE_PX;
  } else if (!slain) {
    const projected = projectedEnd(createdDate, walkedEndDate, rollup.done, rollup.total, dateWindow.end);
    const x2 = (pctForDate(projected, dateWindow) / 100) * width;
    uncharted = wobblePath(x1, x2, laneHeight, seed);
    beastX = x2 + 8;
  }

  const beastXClamped = Math.min(beastX, width - 52);
  const beastY = walked.yAt(Math.min(beastX, width - 30)) - 24;

  const svgClassName =
    "atlas-trail__svg" + (accentKey ? ` atlas-trail__svg--accent-${accentKey}` : "");

  return (
    <div className="atlas-trail" ref={laneRef}>
      <svg className={svgClassName} viewBox={`0 0 ${width} ${laneHeight}`} preserveAspectRatio="none">
        {/* A planned epic has no walked ground to show — only the camp and
            the faint uncharted dots below. */}
        {!planned && <path className="atlas-trail__path" d={walked.d} />}
        {uncharted && (
          <path className="atlas-trail__path atlas-trail__path--uncharted" d={uncharted.d} />
        )}

        <text className="atlas-trail__camp" x={x0 - 8} y={walked.yAt(x0) + 6}>
          ⛺
          {planned && <title>the party has not yet set out</title>}
        </text>

        {doneChildren.map((child) => {
          const wx = (pctForDate(parseCalendarDate(child.updated), dateWindow) / 100) * width;
          const wy = walked.yAt(wx);
          return (
            <g key={child.id} className="atlas-trail__waypoint">
              <circle cx={wx} cy={wy} r={8} />
              <text className="atlas-trail__waypoint-check" x={wx} y={wy + 3.5} textAnchor="middle">
                ✓
              </text>
              <title>{`quest cleared · ${formatDateStamp(parseCalendarDate(child.updated))}`}</title>
            </g>
          );
        })}

        {marching && (
          <g className="atlas-trail__party">
            <circle cx={x1} cy={walked.yAt(x1) - 2} r={12} />
            <text x={x1} y={walked.yAt(x1) + 3} textAnchor="middle">
              ⚔
            </text>
            <title>{`the party — ${rollup.done}/${rollup.total} quests cleared`}</title>
          </g>
        )}

        {parked && (
          <g className="atlas-trail__camped">
            <text x={x1 - 4} y={walked.yAt(x1) - 8}>
              ⛺
            </text>
            <text className="atlas-trail__camped-label" x={x1 + 14} y={walked.yAt(x1) - 8}>
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
    </div>
  );
}

export default AtlasTrail;
