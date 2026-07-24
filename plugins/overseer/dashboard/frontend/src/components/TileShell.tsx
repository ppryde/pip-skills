import type { CSSProperties, ReactNode } from "react";
import { useSortable } from "@dnd-kit/sortable";
import type { BoardCard } from "../api/types";
import { isDragSource } from "../board/dragPlan";
import { checklistWindow } from "../board/checklistWindow";
import { rarityStars } from "../board/rarityStars";
import { formatTokens } from "../board/formatTokens";
import BudgetMeter from "./BudgetMeter";
import DependencyBadge from "./DependencyBadge";
import ChecklistRows from "./ChecklistRows";
import { StarIcon, CheckIcon } from "./icons";

export interface TileShellProps {
  card: BoardCard;
  /** Lane-computed guild accent key (WF-028) — e.g. "backlog",
   * "plan-review", "parked". Declared here in chunk 2's plumbing pass;
   * chunk 3 wires it into the tile's `card-tile--accent-${key}` class. */
  accentKey?: string;
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
  accentKey,
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
  const stars = rarityStars(card.complexity);

  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id: card.id, disabled: sortableDisabled });

  // `max=3` drives the tile's sliding-wheel checklist display (active row
  // centred, neighbours faded) — see checklistWindow's doc comment.
  const { visible: checklistVisible, activeIndex: checklistActiveIndex } =
    checklistWindow(card.checklist, 3);

  // Board-tile progress bar (HANDOFF, in-flight cards only): % MUST derive
  // from the FULL checklist, never `checklistVisible` above — that's a
  // same-shaped-array wrong-source trap (an 8-item checklist's 3-row window
  // has its own, different, done/total ratio). See rarityStars.test.ts's
  // sibling covering test in TileShell.test.tsx.
  const checklistTotal = card.checklist.length;
  const checklistDone = card.checklist.filter((e) => e.status === "completed").length;
  const progressPct =
    checklistTotal > 0 ? Math.round((checklistDone / checklistTotal) * 100) : 0;
  const showProgress = card.status === "in-flight" && checklistTotal > 0;

  // Parked's "no gold" footer (HANDOFF) drops BudgetMeter's numeric value,
  // but the 2x-overbudget tripwire is a warning signal, not a value display
  // — it survives as the same flag BudgetMeter renders (exact class/title,
  // see Board.test.tsx's parked-card tripwire assertion).
  const { estimate: parkedEstimate, actual: parkedActual } = card.budget;
  const parkedTripwire =
    parkedEstimate !== null && parkedEstimate > 0 && parkedActual >= 2 * parkedEstimate;

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
    accentKey ? `card-tile--accent-${accentKey}` : "",
    card.status === "blocked" ? "card-tile--blocked" : "",
    card.status === "done" ? "card-tile--done" : "",
    card.status === "parked" ? "card-tile--parked" : "",
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
          {/* Rarity stars (HANDOFF): complexity S/M/L -> 1-3 filled pips.
              Reserves no space at all when 0 (no complexity set). */}
          {stars > 0 && (
            <span className="card-tile__stars" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <StarIcon
                  key={i}
                  filled={i < stars}
                  className={
                    "card-tile__star " +
                    (i < stars ? "card-tile__star--filled" : "card-tile__star--empty")
                  }
                />
              ))}
            </span>
          )}
          {card.priority && (
            <span className={`priority-chip priority-chip--${card.priority}`}>
              {card.priority}
            </span>
          )}
          {card.repo && <span className="repo-chip">{card.repo}</span>}
          {/*
            Presence-only signal (design spec §5): the board payload carries
            just the holder's bare census session_id, no session_name — so
            the tile shows quiet "claimed" text rather than guessing at a
            label, with the full id available via the title tooltip.
            Staleness dimming needs the sessions poll (drawer-only data), so
            it lives in the drawer's ClaimControl row instead of here — see
            that component's doc comment (deviates from the spec's
            "stale-dimmed tile badge" per the card brief's approved carve-out).
          */}
          {card.claimed_by && (
            <span className="claim-badge" title={card.claimed_by}>
              claimed
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
            className={
              "card-tile__title" + (card.status === "done" ? " card-tile__title--done" : "")
            }
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
          <div
            className={
              "card-tile__title" + (card.status === "done" ? " card-tile__title--done" : "")
            }
          >
            {card.title}
          </div>
        )}
        {/*
          Inert (no button/a/role) — see ChecklistRows's doc comment. It
          lives inside the plain body div above, so it must never introduce
          an interactive element that would nest inside the body's onClick
          target or the title button. `activeIndex` drives the sliding-
          wheel display (active row centred, neighbours faded).
        */}
        {card.checklist.length > 0 && (
          <ChecklistRows
            entries={checklistVisible}
            activeIndex={checklistActiveIndex}
            windowed
          />
        )}
        {/* HANDOFF's board-tile progress bar — in-flight cards with a
            checklist only; % is `checklistDone`/`checklistTotal` above,
            sourced from the full `card.checklist`, never the windowed
            slice. `data-progress-pct` gives tests a stable read on the
            computed value without parsing the inline style. */}
        {showProgress && (
          <div className="card-tile__progress" data-progress-pct={progressPct}>
            <div
              className="card-tile__progress-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        )}
        {children}
        {card.status === "done" ? (
          <div className="card-tile__footer">
            <span className="card-tile__done-badge" aria-hidden="true">
              <CheckIcon />
            </span>
            <span className="card-tile__gold-earned">
              +{formatTokens(card.budget.actual)} gold earned
            </span>
          </div>
        ) : card.status === "parked" ? (
          <div className="card-tile__footer">
            <span className="card-tile__hold-chip">on hold</span>
            {parkedTripwire && (
              <span
                className="budget-meter__flag"
                title="Actual is at least 2x the estimate"
              >
                2x
              </span>
            )}
          </div>
        ) : (
          <div className="card-tile__footer">
            <BudgetMeter budget={card.budget} />
            <DependencyBadge card={card} />
          </div>
        )}
      </div>
    </div>
  );
}

export default TileShell;
