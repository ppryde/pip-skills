import type { ReactNode } from "react";
import type { BoardCard } from "../api/types";
import BudgetMeter from "./BudgetMeter";
import DependencyBadge from "./DependencyBadge";

export interface TileShellProps {
  card: BoardCard;
  /** Extra class(es) on the outer tile (e.g. "epic-card"). */
  variantClassName?: string;
  dimmed?: boolean;
  highlighted?: boolean;
  /** Optional extra header controls (e.g. the epic expand button), right-aligned. */
  headerExtra?: ReactNode;
  /** Optional block rendered between the title and the footer (e.g. the epic rollup line). */
  children?: ReactNode;
}

/**
 * Shared read-only tile chrome for `CardTile` and `EpicCard`: the drag-handle
 * placeholder (Chunk 4 wires @dnd-kit here — ONE place), the header
 * (id + priority chip + BLOCKED badge + optional `headerExtra`), the title,
 * an optional middle slot, and the footer (BudgetMeter + DependencyBadge).
 * The tile body is where Chunk 5's click-to-open-drawer will attach — again,
 * ONE place. Keeping this single means C4/C5 touch this file, not two copies.
 */
function TileShell({
  card,
  variantClassName,
  dimmed = false,
  highlighted = false,
  headerExtra,
  children,
}: TileShellProps) {
  const className = [
    "card-tile",
    variantClassName ?? "",
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
          {headerExtra}
        </div>
        <div className="card-tile__title">{card.title}</div>
        {children}
        <div className="card-tile__footer">
          <BudgetMeter budget={card.budget} />
          <DependencyBadge card={card} />
        </div>
      </div>
    </div>
  );
}

export default TileShell;
