import type { ChangeEvent } from "react";
import { setThreshold } from "../api/client";
import type { UseBoardResult } from "../board/useBoard";
import lastOrders from "../assets/last-orders.png";
import InfoTooltip from "./InfoTooltip";
// WF-097 follow-up: the `<select>` now routes through the design-library
// `<Select/>` primitive (`src/ui/`) — `.threshold-control__select` in
// styles.css is slimmed to its genuine overrides (fixed width, transparent
// background, tighter horizontal padding) now that the rest of its chrome
// duplicates `.qb-select`.
import { Select } from "../ui";

export interface ThresholdControlProps {
  /** Current `context.threshold` — mutate applies the whole board-response,
   * so this always reflects the server's latest value. */
  value: number | null;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
}

/** 5%-step options, 5 through 95 — the full selectable range for the
 * fleet's hand-over threshold. */
const STEP_OPTIONS: number[] = Array.from({ length: 19 }, (_, i) => (i + 1) * 5);

/**
 * A single `<select>` of 5%-step options → `setThreshold(value)` on change,
 * routed through `useBoard().mutate` (never client+setState directly — see
 * wf005-context.md "Single mutation entrypoint"). Applies IMMEDIATELY on
 * selection — no draft state, no Set button, no form submit (WF-090:
 * replaces the old number-input + Set-button pair).
 *
 * WF-042: this is a single GLOBAL value, applied fleet-wide. The
 * user-visible label reads "Last Orders" (the fleet's hand-over cue, with
 * a tankard glyph + an `InfoTooltip` explaining what it means) — but
 * `aria-label="Threshold"` on the `<select>` is left UNCHANGED so existing
 * `getByLabelText("Threshold")` lookups keep working.
 *
 * If the server's current `value` isn't a multiple of 5 (a legacy/manually
 * set threshold), it's added as an extra selected option rather than
 * silently hidden or snapped to the nearest step — the real value stays
 * visible, never masked by opening this dropdown. `value === null` shows a
 * disabled `—` placeholder instead of guessing a default.
 */
function ThresholdControl({ value, mutate, inFlight }: ThresholdControlProps) {
  async function handleChange(e: ChangeEvent<HTMLSelectElement>) {
    const v = Number(e.target.value);
    if (Number.isFinite(v)) {
      await mutate(() => setThreshold(v));
    }
  }

  const options =
    value !== null && !STEP_OPTIONS.includes(value)
      ? [...STEP_OPTIONS, value].sort((a, b) => a - b)
      : STEP_OPTIONS;

  return (
    <div className="threshold-control">
      <span className="threshold-control__title">
        <img
          src={lastOrders}
          className="threshold-control__icon"
          alt=""
          aria-hidden="true"
        />
        Last Orders
        <InfoTooltip label="What is Last Orders?">
          <strong>Last Orders</strong> — the fleet&rsquo;s default hand-over
          line. When a session&rsquo;s context fills past this %, that&rsquo;s
          the cue to wrap up and hand over before it runs dry. Set once here;
          applies to every quest.
        </InfoTooltip>
      </span>
      <Select
        aria-label="Threshold"
        className="threshold-control__select"
        value={value !== null ? String(value) : ""}
        onChange={(e) => void handleChange(e)}
        disabled={inFlight}
      >
        {value === null && (
          <option value="" disabled>
            —
          </option>
        )}
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}%
          </option>
        ))}
      </Select>
    </div>
  );
}

export default ThresholdControl;
