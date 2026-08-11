import { useEffect, useState, type FormEvent } from "react";
import { setThreshold } from "../api/client";
import type { UseBoardResult } from "../board/useBoard";
import lastOrders from "../assets/last-orders.png";
import InfoTooltip from "./InfoTooltip";

export interface ThresholdControlProps {
  /** Current `context.threshold` — mutate applies the whole board-response,
   * so this always reflects the server's latest value. */
  value: number | null;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
}

/**
 * Number input + submit → `setThreshold(value)`, routed through
 * `useBoard().mutate` (never client+setState directly — see
 * wf005-context.md "Single mutation entrypoint"). Reflects the returned
 * `context.threshold` since `mutate` applies the whole board-response.
 *
 * WF-042: this is a single GLOBAL value, applied fleet-wide. The
 * user-visible label reads "Last Orders" (the fleet's hand-over cue, with
 * a tankard glyph + an `InfoTooltip` explaining what it means) rather than
 * "default threshold" — but `aria-label="Threshold"` on the input is left
 * UNCHANGED so existing `getByLabelText("Threshold")` lookups keep working.
 * The title/input/button can't nest inside one `<label>` any more (a
 * `<button>` — the InfoTooltip's trigger — inside a `<label>` is invalid
 * HTML), so the label text is now a plain `<span>` sibling of the input.
 */
function ThresholdControl({ value, mutate, inFlight }: ThresholdControlProps) {
  const [draft, setDraft] = useState(value !== null ? String(value) : "");

  // Keep the draft in sync when the server value changes underneath us
  // (e.g. another client updated it, or the mutation's own response lands).
  useEffect(() => {
    setDraft(value !== null ? String(value) : "");
  }, [value]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const parsed = Number(draft);
    if (draft.trim() === "" || !Number.isFinite(parsed)) return;
    await mutate(() => setThreshold(parsed));
  }

  return (
    <form className="threshold-control" onSubmit={(e) => void handleSubmit(e)}>
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
      <input
        aria-label="Threshold"
        type="number"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        disabled={inFlight}
      />
      <button type="submit" disabled={inFlight}>
        Set
      </button>
    </form>
  );
}

export default ThresholdControl;
