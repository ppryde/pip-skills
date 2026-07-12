import type { CSSProperties, ReactNode } from "react";
import { useSortable } from "@dnd-kit/sortable";
import type { BoardCard } from "../api/types";
import { isDragSource } from "../board/dragPlan";
import BudgetMeter from "./BudgetMeter";
import DependencyBadge from "./DependencyBadge";

export interface TileShellProps {
  card: BoardCard;
  /** Extra class(es) on the outer tile (e.g. "epic-card"). */
  variantClassName?: string;
  dimmed?: boolean;
  highlighted?: boolean;
  /** True while a mutation is in flight — disables the drag handle. */
  dragDisabled?: boolean;
  /** Optional extra header controls (e.g. the epic expand button), right-aligned. */
  headerExtra?: ReactNode;
  /** Optional block rendered between the title and the footer (e.g. the epic rollup line). */
  children?: ReactNode;
  /** Chunk 5: clicking the tile BODY (outside the drag handle) opens the detail drawer. */
  onOpen?: (id: string) => void;
}

/**
 * Shared tile chrome for `CardTile` and `EpicCard`: the drag handle (the
 * ONLY place @dnd-kit's `useSortable` is wired — see wf005-context.md "Drag
 * semantics"), the header (id + priority chip + BLOCKED badge + optional
 * `headerExtra`), the title, an optional middle slot, and the footer
 * (BudgetMeter + DependencyBadge). The tile body (`onOpen`, wired from
 * Chunk 5) is the ONE place a click opens the detail drawer for this card,
 * kept OUTSIDE the handle's listeners so the drawer click and the drag
 * sensor never fight. Only `planned` / non-blocked `in-flight` / `parked`
 * cards (`isDragSource`) get real drag listeners; everything else renders a
 * disabled, inert handle.
 */
function TileShell({
  card,
  variantClassName,
  dimmed = false,
  highlighted = false,
  dragDisabled = false,
  headerExtra,
  children,
  onOpen,
}: TileShellProps) {
  const dragSource = isDragSource(card);
  const sortableDisabled = dragDisabled || !dragSource;

  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id: card.id, disabled: sortableDisabled });

  // No @dnd-kit/utilities per the frozen constraints — build the transform
  // string by hand instead of importing `CSS.Transform.toString`.
  const style: CSSProperties | undefined = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
        transition: transition ?? undefined,
      }
    : transition
      ? { transition }
      : undefined;

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
    <div className={className} data-card-id={card.id} ref={setNodeRef} style={style}>
      <button
        type="button"
        className="card-tile__handle"
        aria-label={dragSource ? "Drag to reorder or move" : "Not draggable"}
        disabled={sortableDisabled}
        {...(sortableDisabled ? {} : { ...attributes, ...listeners })}
      >
        ⠿
      </button>
      {/*
        The body is a PLAIN container (no `role="button"`, no tabIndex): a
        `role="button"` here would nest the interactive `headerExtra` (the
        epic expand button) and the title-open button inside another
        interactive element — an ARIA anti-pattern. Mouse users still open the
        drawer by clicking anywhere in the body via this onClick; keyboard /
        screen-reader users open via the dedicated title `<button>` below,
        which is a SIBLING of `headerExtra`, never its ancestor.
      */}
      <div
        className="card-tile__body"
        onClick={onOpen ? () => onOpen(card.id) : undefined}
      >
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
        {onOpen ? (
          <button
            type="button"
            className="card-tile__title"
            onClick={(e) => {
              // Stop the click reaching the body's onClick so open fires once,
              // and keep the button the single, keyboard-reachable open control.
              e.stopPropagation();
              onOpen(card.id);
            }}
          >
            {card.title}
          </button>
        ) : (
          <div className="card-tile__title">{card.title}</div>
        )}
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
