import { useState, type ChangeEvent } from "react";
import { setParent, setDepends } from "../api/client";
import type { UseBoardResult } from "../board/useBoard";

export interface LinkEditorProps {
  cardId: string;
  parent: string | null;
  dependsOn: string[];
  /** All card ids on the board — used to build the parent/dep option lists.
   * Self is excluded here regardless of whether the caller already did so. */
  allCardIds: string[];
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Called after any mutation settles — the drawer wires this to its
   * counter-guarded `getCard` refetch (see wf005-c6-brief.md). */
  onMutated?: () => void;
}

/**
 * Parent select + dependency add/remove. Every mutating action routes
 * through `useBoard().mutate` — this component never calls the api client +
 * setState itself (see wf005-context.md "Single mutation entrypoint").
 * Null-clear: choosing "— none —" for parent sends `setParent(id, null)`.
 * Deps always send exactly one of `{on}`/`{off}` per call.
 */
function LinkEditor({
  cardId,
  parent,
  dependsOn,
  allCardIds,
  mutate,
  inFlight,
  onMutated,
}: LinkEditorProps) {
  const [addDepId, setAddDepId] = useState("");

  // Exclude self at minimum (per brief); the backend validates cycles.
  const otherCardIds = allCardIds.filter((id) => id !== cardId);
  const depOptions = otherCardIds.filter((id) => !dependsOn.includes(id));

  async function handleParentChange(e: ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value === "" ? null : e.target.value;
    await mutate(() => setParent(cardId, next));
    onMutated?.();
  }

  async function handleAddDep() {
    if (!addDepId) return;
    const on = addDepId;
    await mutate(() => setDepends(cardId, { on }));
    setAddDepId("");
    onMutated?.();
  }

  async function handleRemoveDep(depId: string) {
    await mutate(() => setDepends(cardId, { off: depId }));
    onMutated?.();
  }

  return (
    <div className="link-editor">
      <label className="link-editor__field">
        Parent
        <select
          aria-label="Parent"
          value={parent ?? ""}
          onChange={(e) => void handleParentChange(e)}
          disabled={inFlight}
        >
          <option value="">— none —</option>
          {otherCardIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      </label>

      <div className="link-editor__deps">
        <span className="link-editor__deps-label">Depends on</span>
        <ul className="link-editor__deps-list">
          {dependsOn.map((depId) => (
            <li key={depId}>
              {depId}
              <button
                type="button"
                aria-label={`Remove dependency ${depId}`}
                onClick={() => void handleRemoveDep(depId)}
                disabled={inFlight}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <select
          aria-label="Add dependency"
          value={addDepId}
          onChange={(e) => setAddDepId(e.target.value)}
          disabled={inFlight}
        >
          <option value="">— select —</option>
          {depOptions.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void handleAddDep()}
          disabled={inFlight || !addDepId}
        >
          Add
        </button>
      </div>
    </div>
  );
}

export default LinkEditor;
