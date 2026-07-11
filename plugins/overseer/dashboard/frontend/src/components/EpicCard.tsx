import type { BoardCard } from "../api/types";
import BudgetMeter from "./BudgetMeter";
import DependencyBadge from "./DependencyBadge";

export interface EpicCardProps {
  card: BoardCard;
  expanded: boolean;
  onToggleExpand: (id: string) => void;
  dimmed?: boolean;
  highlighted?: boolean;
}

/**
 * Renders exactly where `layout.ts` placed the epic by its OWN status/stage
 * — same as any card. This component only ADDS a rollup line and an expand
 * affordance; it never nests, hides, or duplicates the epic's children. The
 * "highlight children in place" behaviour lives in the parent (Board), which
 * dims non-children across all lanes — this component just renders the
 * toggle and its own highlighted/dimmed state.
 */
function EpicCard({
  card,
  expanded,
  onToggleExpand,
  dimmed = false,
  highlighted = false,
}: EpicCardProps) {
  const rollup = card.rollup;
  const className = [
    "card-tile",
    "epic-card",
    card.status === "blocked" ? "card-tile--blocked" : "",
    dimmed ? "card-tile--dimmed" : "",
    highlighted ? "card-tile--highlighted" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={className} data-card-id={card.id}>
      <div
        className="card-tile__handle"
        aria-hidden="true"
        title="Drag handle (wired in a later chunk)"
      >
        ⠿
      </div>
      <div className="card-tile__body">
        <div className="card-tile__header">
          <span className="card-tile__id">{card.id}</span>
          {card.priority && (
            <span className={`priority-chip priority-chip--${card.priority}`}>
              {card.priority}
            </span>
          )}
          {card.status === "blocked" && (
            <span className="badge badge--blocked">BLOCKED</span>
          )}
          <button
            type="button"
            className="epic-card__expand"
            onClick={() => onToggleExpand(card.id)}
            aria-expanded={expanded}
          >
            {expanded ? "collapse" : "expand"}
          </button>
        </div>
        <div className="card-tile__title">{card.title}</div>
        {rollup && (
          <div className="epic-card__rollup">
            {rollup.done}/{rollup.total} done · {rollup.actual} vs{" "}
            {rollup.estimate ?? "—"} est.
          </div>
        )}
        <div className="card-tile__footer">
          <BudgetMeter budget={card.budget} />
          <DependencyBadge card={card} />
        </div>
      </div>
    </div>
  );
}

export default EpicCard;
