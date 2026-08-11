import type { BoardCard, Rollup } from "../api/types";
import { rarityStars } from "../board/rarityStars";
import { formatTokens } from "../board/formatTokens";
import { beastFor } from "../board/beastName";
import { formatDateStamp, parseCalendarDate } from "../board/atlasGeometry";
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
  /** Unmet `depends_on` target ids — the page computes doneness across the
   * whole board, this component just renders whatever it's given (same
   * "dumb component" contract as `DependencyBadge`). */
  blockedOn?: string[];
}

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
}: AtlasRailCardProps) {
  const stars = rarityStars(card.complexity);
  const beast = beastFor(card.id);
  const hasChildren = childCards.length > 0;

  // Sub-quest list order matches the trail's own waypoint order (`updated`,
  // TZ-normalized) rather than the children's raw board order.
  const sortedChildren = hasChildren
    ? [...childCards].sort(
        (a, b) => parseCalendarDate(a.updated).getTime() - parseCalendarDate(b.updated).getTime()
      )
    : [];

  const progressPct = rollup.total > 0 ? (rollup.done / rollup.total) * 100 : 0;

  const className = [
    "atlas-rail-card",
    accentKey ? `atlas-rail-card--accent-${accentKey}` : "",
    card.status === "done" ? "atlas-rail-card--done" : "",
    card.status === "parked" ? "atlas-rail-card--parked" : "",
  ]
    .filter(Boolean)
    .join(" ");

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

      <div className="atlas-rail-card__chips">
        <span className="atlas-rail-card__count">
          {rollup.done}/{rollup.total} quests
        </span>
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
        <ul className="atlas-rail-card__subquests">
          {sortedChildren.map((child) => {
            const done = child.status === "done";
            return (
              <li
                key={child.id}
                className={"atlas-rail-card__subquest" + (done ? " atlas-rail-card__subquest--done" : "")}
              >
                <span className="atlas-rail-card__checkbox" aria-hidden="true">
                  {done ? "✓" : ""}
                </span>
                <span
                  className={
                    "atlas-rail-card__subquest-title" +
                    (done ? " atlas-rail-card__subquest-title--done" : "")
                  }
                >
                  {child.title}
                </span>
                <span className="atlas-rail-card__subquest-date">
                  {child.updated ? formatDateStamp(parseCalendarDate(child.updated)) : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default AtlasRailCard;
