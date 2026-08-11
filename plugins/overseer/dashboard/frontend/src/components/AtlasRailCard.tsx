import { useState } from "react";
import type { UIEvent } from "react";
import type { BoardCard, Rollup } from "../api/types";
import { rarityStars } from "../board/rarityStars";
import { formatTokens } from "../board/formatTokens";
import { beastFor } from "../board/beastName";
import { formatDateStamp, parseCalendarDate } from "../board/atlasGeometry";
import {
  openDependencies,
  orderChildrenForTrail,
  statusGroupOf,
  weightOf,
} from "../board/atlasTrailLayout";
import { StarIcon } from "./icons";

export interface AtlasRailCardProps {
  card: BoardCard;
  /** Rollup is non-null by construction — the page (EpicAtlas) only ever
   * builds rail cards for epics that carry one. */
  rollup: Rollup;
  /** The epic's own child cards (`cards.filter(c => c.parent === card.id)`)
   * — named distinctly from React's implicit `children` prop so a JSX
   * `<AtlasRailCard>...</AtlasRailCard>` usage is never mistaken for this. */
  childCards: BoardCard[];
  expanded: boolean;
  onToggleExpand: (id: string) => void;
  onOpen: (id: string) => void;
  /** Lane-computed guild accent key (cardAccent.ts's `accentKeyForCard`) —
   * threaded through as a stable class hook; the later styling chunk owns
   * the actual colour. */
  accentKey?: string;
  /** Unmet `depends_on` target ids for the EPIC itself — the page computes
   * doneness across the whole board, this component just renders whatever
   * it's given (same "dumb component" contract as `DependencyBadge`). */
  blockedOn?: string[];
  /** Every card on the board, keyed by id — needed to resolve each CHILD's
   * own `depends_on` for the checklist row's blocked (⛔) styling. Defaults
   * to empty so existing call sites that never pass it just render every
   * child as never-blocked, rather than crashing. */
  cardsById?: Map<string, BoardCard>;
}

function weightLabel(child: BoardCard): string {
  return "★".repeat(weightOf(child));
}

/** ~5 rows of the checklist wheel (HANDOFF: "~132px desktop / ~224px
 * mobile") — mobile's own cap is a pure CSS override
 * (`.atlas-rail-card__subquests` inside the `@media (max-width: 720px)`
 * block), this constant only drives the desktop default and the
 * overflow-detection math below (both caps land on the SAME element, so
 * either is a valid "does this list currently overflow" probe). */
const WHEEL_MAX_HEIGHT_PX = 132;

/**
 * Left-rail quest card for one epic in the Epic Atlas (WF-086) — the
 * board's card-tile sticker language, minus TileShell's drag machinery
 * (rail cards never move) and its own-`checklist` rendering (the atlas
 * rail shows the epic's CHILD CARDS, not a task checklist). Every
 * `.atlas-rail-card__*` class is a stable hook for the later styling chunk
 * — unstyled until then is expected.
 */
function AtlasRailCard({
  card,
  rollup,
  childCards,
  expanded,
  onToggleExpand,
  onOpen,
  accentKey,
  blockedOn = [],
  cardsById = new Map(),
}: AtlasRailCardProps) {
  const stars = rarityStars(card.complexity);
  const beast = beastFor(card.id);
  const hasChildren = childCards.length > 0;

  // Sub-quest list order matches the TRAIL's own order (WF-086 v2: done ->
  // in-progress -> todo, by board `order` within each group) — not the old
  // date-sorted order — so the rail card's checklist and its own trail row
  // never disagree about sequence.
  const orderedChildren = hasChildren ? orderChildrenForTrail(childCards) : [];

  const progressPct = rollup.total > 0 ? (rollup.done / rollup.total) * 100 : 0;

  const className = [
    "atlas-rail-card",
    accentKey ? `atlas-rail-card--accent-${accentKey}` : "",
    card.status === "done" ? "atlas-rail-card--done" : "",
    card.status === "parked" ? "atlas-rail-card--parked" : "",
  ]
    .filter(Boolean)
    .join(" ");

  // Checklist wheel (HANDOFF): real scroll-position-driven fade masks
  // (`.fade-top`/`.fade-bottom` in the prototype) rather than the
  // prototype's own imperative `dataset`-guarded DOM listener wiring —
  // React's `onScroll` prop is already idempotent (React itself owns
  // attaching/detaching the single listener across re-renders; there's no
  // manual `querySelectorAll` + guard-flag re-wiring step to port). State
  // starts at "no fade either side" and both `useState` initial reads AND
  // every `onScroll` firing run the exact same `computeFades` — jsdom (no
  // real layout) reports 0/0/0 for scrollHeight/clientHeight/scrollTop
  // unless a test stubs them, so both fades correctly stay off by default
  // there.
  const [fadeTop, setFadeTop] = useState(false);
  const [fadeBottom, setFadeBottom] = useState(false);

  function computeFades(el: HTMLElement) {
    setFadeTop(el.scrollTop > 1);
    setFadeBottom(el.scrollTop + el.clientHeight < el.scrollHeight - 1);
  }

  function handleSubquestsRef(el: HTMLUListElement | null) {
    if (el) computeFades(el);
  }

  function handleSubquestsScroll(e: UIEvent<HTMLUListElement>) {
    computeFades(e.currentTarget);
  }

  return (
    <div className={className} data-card-id={card.id} onClick={() => onOpen(card.id)}>
      <div className="atlas-rail-card__top">
        <span className="atlas-rail-card__id">{card.id}</span>
        {stars > 0 && (
          <span className="atlas-rail-card__stars" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <StarIcon
                key={i}
                filled={i < stars}
                className={
                  "atlas-rail-card__star " +
                  (i < stars ? "atlas-rail-card__star--filled" : "atlas-rail-card__star--empty")
                }
              />
            ))}
          </span>
        )}
      </div>

      <div
        className={
          "atlas-rail-card__title" + (card.status === "done" ? " atlas-rail-card__title--done" : "")
        }
      >
        {card.title}
      </div>

      {/* Hidden (not omitted) at mobile widths — condensed-set contract,
          see HANDOFF's "Responsive (required)" section. */}
      <div className="atlas-rail-card__vs">vs {beast.name}</div>

      {/* The n/m count is a SIBLING of, not nested inside, `.atlas-rail-
          card__chips` — HANDOFF's condensed mobile set explicitly keeps
          "progress track + n/m count" visible and hides only the gold/lock
          chips, so the count needs its own place the mobile
          `.atlas-rail-card__chips { display: none }` rule can never reach
          by being its ancestor. */}
      <span className="atlas-rail-card__count">
        {rollup.done}/{rollup.total} quests
      </span>

      <div className="atlas-rail-card__chips">
        <span className="atlas-rail-card__gold">🪙 {formatTokens(rollup.actual)}</span>
        {blockedOn.length > 0 && (
          <span className="atlas-rail-card__lock" title={`Locked behind ${blockedOn.join(", ")}`}>
            🔒 {blockedOn.join(", ")}
          </span>
        )}
      </div>

      <div className="atlas-rail-card__progress" data-progress-pct={Math.round(progressPct)}>
        <div className="atlas-rail-card__progress-fill" style={{ width: `${progressPct}%` }} />
      </div>

      {hasChildren && (
        <button
          type="button"
          className="atlas-rail-card__expand"
          aria-expanded={expanded}
          onClick={(e) => {
            // Same stopPropagation pattern as EpicCard.tsx's expand button —
            // expanding sub-quests is distinct from opening the drawer, even
            // though the button lives inside the onOpen-wired card body.
            e.stopPropagation();
            onToggleExpand(card.id);
          }}
        >
          {expanded ? "▾" : "▸"} sub-quests
        </button>
      )}

      {expanded && hasChildren && (
        <ul
          className={
            "atlas-rail-card__subquests" +
            (fadeTop ? " atlas-rail-card__subquests--fade-top" : "") +
            (fadeBottom ? " atlas-rail-card__subquests--fade-bottom" : "")
          }
          style={{ maxHeight: WHEEL_MAX_HEIGHT_PX }}
          ref={handleSubquestsRef}
          onScroll={handleSubquestsScroll}
        >
          {orderedChildren.map((child) => {
            const done = child.status === "done";
            const abandoned = child.status === "abandoned";
            const group = statusGroupOf(child);
            // Impl-review round 1, finding 6: restricted to the "todo"
            // group specifically (not "in-progress" too, as a bare
            // `group !== "done"` let through) — an ACTIVELY-WORKED quest
            // isn't "barred", it's already underway (the trail renders it
            // AT HAND, not as a boulder), so the checklist must agree.
            // Stale depends_on data on already-finished work is excluded
            // for the same "can't meaningfully still be blocked" reason.
            // The card's own 🔒 "locked behind" chip already communicates
            // the dependency regardless of this row-level styling.
            const blocked = group === "todo" && openDependencies(child, cardsById).length > 0;

            const rowClassName = [
              "atlas-rail-card__subquest",
              done ? "atlas-rail-card__subquest--done" : "",
              abandoned ? "atlas-rail-card__subquest--abandoned" : "",
              blocked ? "atlas-rail-card__subquest--blocked" : "",
            ]
              .filter(Boolean)
              .join(" ");

            const checkboxGlyph = done ? "✓" : abandoned ? "†" : blocked ? "⛔" : "";

            const titleClassName = [
              "atlas-rail-card__subquest-title",
              done ? "atlas-rail-card__subquest-title--done" : "",
              abandoned ? "atlas-rail-card__subquest-title--abandoned" : "",
            ]
              .filter(Boolean)
              .join(" ");

            // Done/abandoned work has a real date; a todo (or in-progress,
            // or blocked-overlay) child has no honest date to show — the
            // ledger keeps no due dates, so showing one would imply a
            // deadline that was never made (HANDOFF).
            const stamp =
              done || abandoned ? formatDateStamp(parseCalendarDate(child.updated)) : weightLabel(child);

            return (
              <li key={child.id} className={rowClassName}>
                <span className="atlas-rail-card__checkbox" aria-hidden="true">
                  {checkboxGlyph}
                </span>
                <span className={titleClassName}>{child.title}</span>
                <span className="atlas-rail-card__subquest-date">{stamp}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default AtlasRailCard;
