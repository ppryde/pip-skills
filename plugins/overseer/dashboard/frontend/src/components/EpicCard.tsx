import type { BoardCard } from "../api/types";
import {
  orderChildrenForTrail,
  statusGroupOf,
  weightOf,
  openDependencies,
} from "../board/atlasTrailLayout";
import { formatDateStamp, parseCalendarDate } from "../board/atlasGeometry";
import TileShell from "./TileShell";

export interface EpicCardProps {
  card: BoardCard;
  accentKey?: string;
  expanded: boolean;
  onToggleExpand: (id: string) => void;
  dimmed?: boolean;
  highlighted?: boolean;
  branchDimmed?: boolean;
  branchSpotlight?: boolean;
  glowing?: boolean;
  dragDisabled?: boolean;
  onOpen?: (id: string) => void;
  colorRegistry?: Record<string, string>;
  /** The epic's own child cards (Board derives these via groupChildrenByEpic). */
  childCards?: BoardCard[];
  /** Whole-board id→card map, to resolve each child's blocked state. */
  cardsById?: Map<string, BoardCard>;
}

/**
 * Board epic tile. Composes the shared TileShell (so it inherits the two-row
 * header, rollup-sum coins, seal/edge via `.epic-card`) and ADDS, in the
 * children slot, a bottom bar (quest count + expand toggle) and — when
 * expanded — an inline quest-log of the epic's sub-quests. The expand toggle
 * drives the SAME `expanded`/`onToggleExpand` state that also highlights the
 * epic's children across lanes (Board/Lane, unchanged).
 */
function EpicCard({
  card,
  accentKey,
  expanded,
  onToggleExpand,
  dimmed = false,
  highlighted = false,
  branchDimmed = false,
  branchSpotlight = false,
  glowing = false,
  dragDisabled = false,
  onOpen,
  colorRegistry,
  childCards = [],
  cardsById = new Map(),
}: EpicCardProps) {
  const rollup = card.rollup;
  const hasChildren = childCards.length > 0;
  const ordered = hasChildren ? orderChildrenForTrail(childCards) : [];

  return (
    <TileShell
      card={card}
      accentKey={accentKey}
      variantClassName="epic-card"
      dimmed={dimmed}
      highlighted={highlighted}
      branchDimmed={branchDimmed}
      branchSpotlight={branchSpotlight}
      glowing={glowing}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
      colorRegistry={colorRegistry}
    >
      <div className="epic-card__foot">
        {rollup && (
          <span className="epic-card__count">
            {rollup.done} / {rollup.total} quests
          </span>
        )}
        {hasChildren && (
          <button
            type="button"
            className="epic-card__expand"
            aria-expanded={expanded}
            onClick={(e) => {
              // Distinct from opening the drawer — expanding drives the epic's
              // sub-quest log AND its cross-lane child highlight.
              e.stopPropagation();
              onToggleExpand(card.id);
            }}
          >
            {expanded ? "▾" : "▸"} sub-quests
          </button>
        )}
      </div>

      {expanded && hasChildren && (
        <ul className="epic-card__subquests">
          {ordered.map((child) => {
            const done = child.status === "done";
            const abandoned = child.status === "abandoned";
            const group = statusGroupOf(child); // "done" | "in-progress" | "todo"
            const inProgress = group === "in-progress";
            const blocked = group === "todo" && openDependencies(child, cardsById).length > 0;

            const glyph = done ? "✓" : abandoned ? "†" : blocked ? "⛔" : inProgress ? "⚔" : "◦";
            const stamp =
              done || abandoned
                ? formatDateStamp(parseCalendarDate(child.updated))
                : "★".repeat(weightOf(child));

            const rowClassName = [
              "epic-card__subquest",
              done ? "epic-card__subquest--done" : "",
              abandoned ? "epic-card__subquest--abandoned" : "",
              inProgress ? "epic-card__subquest--prog" : "",
              blocked ? "epic-card__subquest--blocked" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <li key={child.id} className={rowClassName}>
                <span className="epic-card__subquest-glyph" aria-hidden="true">
                  {glyph}
                </span>
                <span className="epic-card__subquest-title">
                  {child.title}
                  {inProgress && <span className="epic-card__athand">AT HAND</span>}
                </span>
                <span className="epic-card__subquest-meta">{stamp}</span>
              </li>
            );
          })}
        </ul>
      )}
    </TileShell>
  );
}

export default EpicCard;
