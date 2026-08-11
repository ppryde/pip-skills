import { useState, type ChangeEvent } from "react";
import type { FilterState } from "../board/cardFilter";
import LabelFilterPopover from "./LabelFilterPopover";

export interface FilterBarProps {
  filter: FilterState;
  /** Distinct labels across the board (`cardFilter.distinctLabels`) — passed
   * straight through to `LabelFilterPopover` when it's open. */
  labels: string[];
  visibleCount: number;
  totalCount: number;
  /** Whether `filter` still equals `DEFAULT_FILTER` — the caller's
   * equality check, not ours; only gates the "Clear filters" button here. */
  isDefault: boolean;
  onQuery: (query: string) => void;
  onCycleLabel: (label: string) => void;
  onPriority: (priority: string | null) => void;
  onComplexity: (complexity: string | null) => void;
  onClear: () => void;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * passed straight through to `LabelFilterPopover` when it's open. */
  colorRegistry?: Record<string, string>;
  /** WF-085b: App-owned mobile "Controls ▾" collapse state (shared with
   * TopBar's own `#topbar-controls-group`) — this component's root element
   * carries `id="filter-bar"` + `hidden={!controlsOpen}` so ONE toggle
   * folds search/priority/complexity/labels/Clear away on mobile alongside
   * TopBar's group. styles.css confines the `[hidden]` override to the
   * ≤720px media query, so desktop always renders this bar regardless of
   * the flag (mirrors `#topbar-controls-group`'s existing pattern). */
  controlsOpen: boolean;
}

const PRIORITIES = ["P0", "P1", "P2", "P3", "P4"];
const COMPLEXITIES = ["S", "M", "L", "XL"];

/**
 * The board's filter row (F3, WF-061): search + priority/complexity
 * dropdowns + a Labels button that folds out `LabelFilterPopover`, plus a
 * right-aligned visible/total readout and Clear filters. Purely presentational —
 * `filter` is the caller's source of truth (same deferred-state pattern as
 * `LabelFilterPopover`/`LabelEditor`/`StatusMenu`); this component owns only
 * the popover's open/closed `useState`, nothing about filter values.
 *
 * `LabelFilterPopover` renders as a full-backdrop overlay (`PartyOverlay`
 * convention), so toggling it needs no anchor/positioning math here — just a
 * boolean and a conditional render.
 */
function FilterBar({
  filter,
  labels,
  visibleCount,
  totalCount,
  isDefault,
  onQuery,
  onCycleLabel,
  onPriority,
  onComplexity,
  onClear,
  colorRegistry,
  controlsOpen,
}: FilterBarProps) {
  const [labelsOpen, setLabelsOpen] = useState(false);
  const labelBadge = filter.includeLabels.length + filter.excludeLabels.length;

  function handlePriorityChange(e: ChangeEvent<HTMLSelectElement>) {
    onPriority(e.target.value === "" ? null : e.target.value);
  }

  function handleComplexityChange(e: ChangeEvent<HTMLSelectElement>) {
    onComplexity(e.target.value === "" ? null : e.target.value);
  }

  return (
    <div id="filter-bar" className="filter-bar" hidden={!controlsOpen}>
      <input
        className="filter-bar__search"
        aria-label="search"
        type="search"
        placeholder="Search cards…"
        value={filter.query}
        onChange={(e) => onQuery(e.target.value)}
      />

      <label className="filter-bar__select">
        Priority
        <select
          aria-label="priority"
          value={filter.priority ?? ""}
          onChange={handlePriorityChange}
        >
          <option value="">None</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>

      <label className="filter-bar__select">
        Complexity
        <select
          aria-label="complexity"
          value={filter.complexity ?? ""}
          onChange={handleComplexityChange}
        >
          <option value="">None</option>
          {COMPLEXITIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        className="filter-bar__labels-btn"
        onClick={() => setLabelsOpen((open) => !open)}
      >
        Labels
        {labelBadge > 0 && (
          <span className="filter-bar__labels-badge">{labelBadge}</span>
        )}
      </button>

      <div className="filter-bar__count">
        {visibleCount} of {totalCount}
        <button
          type="button"
          className="filter-bar__clear-btn"
          onClick={onClear}
          disabled={isDefault}
        >
          Clear filters
        </button>
      </div>

      {labelsOpen && (
        <LabelFilterPopover
          labels={labels}
          includeLabels={filter.includeLabels}
          excludeLabels={filter.excludeLabels}
          onCycle={onCycleLabel}
          onClose={() => setLabelsOpen(false)}
          colorRegistry={colorRegistry}
        />
      )}
    </div>
  );
}

export default FilterBar;
