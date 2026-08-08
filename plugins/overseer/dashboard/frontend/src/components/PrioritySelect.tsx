import type { ChangeEvent } from "react";
import { setPriority } from "../api/client";
import type { Priority } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";

export interface PrioritySelectProps {
  cardId: string;
  value: Priority | null;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Called after the mutation settles — the drawer wires this to its
   * counter-guarded `getCard` refetch (see wf005-c6-brief.md). */
  onMutated?: () => void;
}

const PRIORITIES: Priority[] = ["P0", "P1", "P2", "P3"];

/**
 * P0..P3 + a "clear" option. Routes through `useBoard().mutate` — this
 * component NEVER calls the api client + setState itself (see
 * wf005-context.md "Single mutation entrypoint").
 */
function PrioritySelect({
  cardId,
  value,
  mutate,
  inFlight,
  onMutated,
}: PrioritySelectProps) {
  async function handleChange(e: ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value === "" ? null : (e.target.value as Priority);
    await mutate(() => setPriority(cardId, next));
    onMutated?.();
  }

  return (
    <select
      className="priority-select"
      aria-label="Priority"
      value={value ?? ""}
      onChange={(e) => void handleChange(e)}
      disabled={inFlight}
    >
      <option value="">— none —</option>
      {PRIORITIES.map((p) => (
        <option key={p} value={p}>
          {p}
        </option>
      ))}
    </select>
  );
}

export default PrioritySelect;
