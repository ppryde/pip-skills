import { useEffect, useState, type FormEvent } from "react";
import { setThreshold } from "../api/client";
import type { UseBoardResult } from "../board/useBoard";

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
      <label className="threshold-control__label">
        threshold
        <input
          aria-label="Threshold"
          type="number"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={inFlight}
        />
      </label>
      <button type="submit" disabled={inFlight}>
        Set
      </button>
    </form>
  );
}

export default ThresholdControl;
