import { useState, type ChangeEvent } from "react";
import { setParent, setDepends } from "../api/client";
import type { UseBoardResult } from "../board/useBoard";
// WF-097 follow-up: the parent/add-dependency selects and the "Add" button
// now route through the design-library primitives (`src/ui/`) —
// `.link-editor select` in styles.css is slimmed to its genuine overrides
// now that most of its chrome duplicates `.qb-select`. The per-dependency
// remove "×" glyph is left as a bare `<button>` — it's a bespoke round
// icon-only affordance (`.link-editor__deps-list button`, too small for a
// rectangular Role-A outline — see that rule's own WF-046 item 2 comment),
// not a `.qb-btn` shape, so it doesn't fit `<Button/>`.
import { Button, Select } from "../ui";

export interface LinkEditorProps {
  cardId: string;
  parent: string | null;
  dependsOn: string[];
  /** All card ids on the board — used to build the parent/dep option lists.
   * Self is excluded here regardless of whether the caller already did so. */
  allCardIds: string[];
  /** id -> title lookup (WF-081) for the same board `allCardIds` draws from.
   * Optional/best-effort: an id missing from the map (or the map itself
   * being omitted) just falls back to showing the bare id, same as before. */
  cardTitles?: Record<string, string>;
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
  cardTitles,
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
        <Select
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
        </Select>
      </label>

      <div className="link-editor__deps">
        <span className="link-editor__deps-label">Depends on</span>
        <ul className="link-editor__deps-list">
          {dependsOn.map((depId) => (
            <li key={depId}>
              {depId}
              {cardTitles?.[depId] ? (
                <span style={{ opacity: 0.65, fontSize: "0.85em" }}>
                  {" "}
                  — {cardTitles[depId]}
                </span>
              ) : null}
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
        <Select
          aria-label="Add dependency"
          value={addDepId}
          onChange={(e) => setAddDepId(e.target.value)}
          disabled={inFlight}
        >
          <option value="">— select —</option>
          {depOptions.map((id) => {
            const title = cardTitles?.[id];
            // `<option>` is text-only content in HTML — it cannot hold a
            // nested `<span>` (browsers won't apply per-substring styling
            // inside a native select popup regardless), so the title is
            // appended as plain text rather than a styled child element.
            return (
              <option key={id} value={id}>
                {title ? `${id} — ${title}` : id}
              </option>
            );
          })}
        </Select>
        <Button onClick={() => void handleAddDep()} disabled={inFlight || !addDepId}>
          Add
        </Button>
      </div>
    </div>
  );
}

export default LinkEditor;
