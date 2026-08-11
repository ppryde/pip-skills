import { useState, type ChangeEvent } from "react";
import type { FilterState } from "../board/cardFilter";
import LabelFilterPopover from "./LabelFilterPopover";
import scryIcon from "../assets/ui-icons/scry.png";

export interface FilterBarProps {
  filter: FilterState;
  /** Distinct labels across the board (`cardFilter.distinctLabels`) — passed
   * straight through to `LabelFilterPopover` when it's open. */
  labels: string[];
  visibleCount: number;
  totalCount: number;
  /** Whether `filter` still equals `DEFAULT_FILTER` — the caller's
   * equality check, not ours; only gates the "Clear" button here. */
  isDefault: boolean;
  onQuery: (query: string) => void;
  onCycleLabel: (label: string) => void;
  onPriority: (priority: string | null) => void;
  onComplexity: (complexity: string | null) => void;
  onClear: () => void;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * passed straight through to `LabelFilterPopover` when it's open. */
  colorRegistry?: Record<string, string>;
  /** App-owned "Filters ▾" collapse state (its own independent toggle now —
   * see TopBar's `[Filters ▾] [Controls ▾] [＋]` cluster, split from the
   * old shared "Controls ▾"). This component's root element carries
   * `id="filter-bar"` + `hidden={!filtersOpen}`; the `hidden` override now
   * takes effect on every viewport, not just ≤720px (desktop defaults open
   * so the board looks unchanged on load, but the Filters button can
   * collapse this bar there too). */
  filtersOpen: boolean;
}

const PRIORITIES = ["P0", "P1", "P2", "P3", "P4"];
const COMPLEXITIES = ["S", "M", "L", "XL"];

/**
 * The board's filter row (F3, WF-061): a "Scry" eyebrow header line — "Scry"
 * on the left, the visible/total readout on the right
 * (`.filter-bar__eyebrow-row`, `justify-content: space-between`) — then
 * search on its own line, then priority/complexity dropdowns + a Labels
 * button (that folds out `LabelFilterPopover`) + a "Clear" button, grouped
 * together on the line below that (`.filter-bar__facets`; "Clear" sits at
 * the far end, after Labels). Purely presentational — `filter` is
 * the caller's source of truth (same deferred-state pattern as
 * `LabelFilterPopover`/`LabelEditor`/`StatusMenu`); this component owns only
 * the popover's open/closed `useState`, nothing about filter values.
 *
 * WF-092: priority/complexity no longer carry a standalone visible label —
 * the field name is the select's own `value=""` placeholder option (e.g.
 * "Priority"), so the wrapper is a plain `<div className="filter-bar__select">`
 * rather than a `<label>` around visible text. Each `<select>` keeps its own
 * `aria-label` for accessibility.
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
  filtersOpen,
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
    <div id="filter-bar" className="filter-bar" hidden={!filtersOpen}>
      {/* Own line above the row below (`.filter-bar__eyebrow-row`'s
          `flex-basis: 100%` forces the wrap) — was inline before search.
          Task B: the visible/total count sits at the RIGHT-HAND end of this
          same line (`justify-content: space-between` on the row), so it
          reads as one section-header line: "Scry" … "N of M" — rather than
          the count being buried down among the filter controls below.
          Coordinator follow-up: "Clear" (was "Clear filters") no longer
          lives here — it moved to the end of `.filter-bar__facets` below. */}
      <div className="filter-bar__eyebrow-row">
        <span className="filter-bar__eyebrow-title">
          <img src={scryIcon} alt="" className="filter-bar__eyebrow-icon" />
          <span className="filter-bar__eyebrow">Scry</span>
        </span>

        <div className="filter-bar__count">{visibleCount} of {totalCount}</div>
      </div>

      <div className="filter-bar__row">
        <input
          className="filter-bar__search"
          aria-label="search"
          type="search"
          placeholder="Search cards…"
          value={filter.query}
          onChange={(e) => onQuery(e.target.value)}
        />

        {/* Priority/Complexity/Labels/Clear grouped onto their own line
            below search — `.filter-bar__facets`'s `flex-basis: 100%` forces
            the wrap inside `.filter-bar__row` (same trick as
            `.filter-bar__eyebrow-row` above it), leaving search alone on the
            line above. */}
        <div className="filter-bar__facets">
          <div className="filter-bar__select">
            <select
              aria-label="priority"
              value={filter.priority ?? ""}
              onChange={handlePriorityChange}
            >
              <option value="">Priority</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-bar__select">
            <select
              aria-label="complexity"
              value={filter.complexity ?? ""}
              onChange={handleComplexityChange}
            >
              <option value="">Complexity</option>
              {COMPLEXITIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

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

          {/* Moved off the Scry eyebrow line onto the end of this row
              (coordinator follow-up) — same class/onClick/disabled as
              before, just relocated + shortened to "Clear" (exact-match,
              distinct from the topbar's own "Clear…"/ClearDialog button —
              see FilterBar.test.tsx/App.test.tsx). */}
          <button
            type="button"
            className="filter-bar__clear-btn"
            onClick={onClear}
            disabled={isDefault}
          >
            Clear
          </button>
        </div>
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
