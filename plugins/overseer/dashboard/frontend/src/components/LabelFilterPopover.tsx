import { useEffect } from "react";
import { labelColor } from "../board/labelColor";

export interface LabelFilterPopoverProps {
  /** All distinct labels across the board (`cardFilter.distinctLabels`) —
   * one chip per entry, in the order given (already sorted by the caller). */
  labels: string[];
  includeLabels: string[];
  excludeLabels: string[];
  /** Advances a single label's tri-state (neutral -> include -> exclude ->
   * neutral) — wired straight to `useCardFilter().cycleLabel`. This
   * component owns no state of its own; `includeLabels`/`excludeLabels`
   * always reflect the caller's source of truth, same deferred-state
   * pattern as `LabelEditor`/`StatusMenu`. */
  onCycle: (label: string) => void;
  onClose: () => void;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * threaded through to `labelColor` so a filter chip keeps its
   * registry-chosen colour, not just the hash-palette fallback. */
  colorRegistry?: Record<string, string>;
}

type ChipState = "include" | "exclude" | "neutral";

function chipState(
  label: string,
  includeLabels: string[],
  excludeLabels: string[]
): ChipState {
  if (includeLabels.includes(label)) return "include";
  if (excludeLabels.includes(label)) return "exclude";
  return "neutral";
}

/**
 * Tri-state label filter popover (F3 fold-in, WF-060). One chip per distinct
 * board label; clicking a chip calls `onCycle`, which the caller's
 * `useCardFilter().cycleLabel` advances neutral -> include -> exclude ->
 * neutral. Each chip keeps its established `label-chip--<key>` palette
 * colour (`board/labelColor.ts`'s stable hash, same as `LabelChips`/
 * `LabelEditor`) so a label reads consistently everywhere on the board; the
 * `label-filter-chip--<state>` modifier layers the include/exclude cue on
 * top without overriding that palette.
 *
 * Follows `PartyOverlay`'s backdrop convention (the codebase's only close
 * idiom for a dismissible layer): the outer backdrop closes on click, the
 * inner `.label-filter-popover` sheet stops propagation so a click inside
 * never closes it, and Escape closes from anywhere while it's open.
 */
function LabelFilterPopover({
  labels,
  includeLabels,
  excludeLabels,
  onCycle,
  onClose,
  colorRegistry,
}: LabelFilterPopoverProps) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="label-filter-popover-backdrop"
      data-testid="label-filter-popover-backdrop"
      onClick={onClose}
    >
      <div
        className="label-filter-popover"
        role="dialog"
        aria-label="Filter by label"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="label-filter-popover__legend">
          ✓ include · ✕ exclude
        </div>
        {labels.map((label) => {
          const state = chipState(label, includeLabels, excludeLabels);
          return (
            <button
              key={label}
              type="button"
              className={`label-filter-chip label-filter-chip--${state} label-chip--${labelColor(
                label,
                colorRegistry
              )}`}
              aria-label={`${label}: ${state}`}
              onClick={() => onCycle(label)}
            >
              {label}
              {state === "include" && " ✓"}
              {state === "exclude" && " ✕"}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default LabelFilterPopover;
