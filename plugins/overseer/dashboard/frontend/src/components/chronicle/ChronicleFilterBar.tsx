/**
 * The Chronicle's filters, in the top bar's filter region — the same slot,
 * id and collapse the board's `<FilterBar/>` uses, so "Filters ▾" reveals
 * whichever page's filters apply. App.tsx renders exactly one of the two.
 *
 * Only the time window lives here. Repo and branch scope come from the top
 * bar's own repo and branch selectors, which drive the Chronicle directly on
 * this page (the repo selector gains an "All repos" choice there). The last
 * sync's note sits where the board's "N of M" count does, so the eyebrow row
 * reads the same way on both pages.
 */
import { Button, Label } from "../../ui";
import scrollIcon from "../../assets/ui-icons/scroll.png";

/** A day count (a fixed rolling window), `"month-to-date"` (recomputed at
 * request time from the 1st of the current month — see `chronicleQuery` in
 * api/client.ts), or `undefined` for all time. */
export type ChronicleTimeWindow = number | "month-to-date" | undefined;

export const CHRONICLE_WINDOWS: { label: string; window: ChronicleTimeWindow }[] = [
  { label: "7 days", window: 7 },
  { label: "30 days", window: 30 },
  { label: "90 days", window: 90 },
  { label: "Month to date", window: "month-to-date" },
  { label: "All time", window: undefined },
];

export interface ChronicleFilterBarProps {
  timeWindow: ChronicleTimeWindow;
  onTimeWindow: (window: ChronicleTimeWindow) => void;
  syncNote: string | null;
  /** App-owned "Filters ▾" collapse state, shared with the board's bar. */
  filtersOpen: boolean;
}

export default function ChronicleFilterBar({
  timeWindow,
  onTimeWindow,
  syncNote,
  filtersOpen,
}: ChronicleFilterBarProps) {
  return (
    <div
      id="filter-bar"
      className="filter-bar filter-bar--chronicle"
      hidden={!filtersOpen}
      role="group"
      aria-label="Chronicle filters"
    >
      <div className="filter-bar__eyebrow-row">
        <span className="filter-bar__eyebrow-title">
          <img src={scrollIcon} alt="" className="filter-bar__eyebrow-icon" />
          <Label className="filter-bar__eyebrow">Chronicle</Label>
        </span>
        {syncNote && (
          <div className="filter-bar__count" role="status">
            {syncNote}
          </div>
        )}
      </div>

      <div className="filter-bar__row">
        <div className="chronicle__segment" role="group" aria-label="Time window">
          {CHRONICLE_WINDOWS.map((w) => (
            <Button
              key={w.label}
              aria-pressed={timeWindow === w.window}
              onClick={() => onTimeWindow(w.window)}
              className="chronicle__seg-btn"
            >
              {w.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
