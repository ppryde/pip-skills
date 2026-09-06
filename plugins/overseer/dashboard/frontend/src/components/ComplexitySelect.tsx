import type { ChangeEvent } from "react";
import { setAttributes } from "../api/client";
import type { UseBoardResult } from "../board/useBoard";
import { Select } from "../ui";

export interface ComplexitySelectProps {
  cardId: string;
  value: string | null;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Called after the mutation settles — the drawer wires this to its
   * counter-guarded `getCard` refetch, as for PrioritySelect. */
  onMutated?: () => void;
}

const COMPLEXITIES = ["S", "M", "L", "XL"];

/**
 * WF-070: S/M/L/XL + a "clear" option, the twin of PrioritySelect. Routes
 * through `useBoard().mutate` — never the api client + setState itself
 * (wf005-context.md "Single mutation entrypoint").
 */
function ComplexitySelect({ cardId, value, mutate, inFlight, onMutated }: ComplexitySelectProps) {
  async function handleChange(e: ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value === "" ? null : e.target.value;
    await mutate(() => setAttributes(cardId, { complexity: next }));
    onMutated?.();
  }

  return (
    <Select
      className="priority-select"
      aria-label="Complexity"
      value={value ?? ""}
      onChange={(e) => void handleChange(e)}
      disabled={inFlight}
    >
      <option value="">— size —</option>
      {COMPLEXITIES.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </Select>
  );
}

export default ComplexitySelect;
