import { useState, type KeyboardEvent } from "react";
import { labelColor } from "../board/labelColor";

export interface LabelEditorProps {
  labels: string[];
  /** Full-replace semantics, same as the backend's `POST /api/card/{id}/labels`
   * (via the existing `setLabels` client call) — always called with the
   * COMPLETE new label set, never a delta. */
  onSave: (labels: string[]) => Promise<void>;
}

/**
 * Editable label control (F1 fold-in, WF-058) — chips with a per-chip remove
 * plus an add-input that commits on Enter. Every mutation (add/remove) calls
 * `onSave` with the full new set immediately; there is no separate "save"
 * step and no local optimistic label state — `labels` always reflects the
 * caller's source of truth, same pattern as the drawer's other mutation
 * controls (PrioritySelect/StatusMenu/LinkEditor) deferring to their own
 * props rather than tracking a shadow copy.
 *
 * Each chip carries the SAME `label-chip label-chip--<key>` classes the
 * read-only `LabelChips` uses (`board/labelColor.ts`'s stable hash), so an
 * edited label keeps its established colour — `.label-editor__chip` in
 * styles.css only adds the layout needed to sit the remove glyph inline,
 * it never overrides the palette itself.
 */
function LabelEditor({ labels, onSave }: LabelEditorProps) {
  const [draft, setDraft] = useState("");

  const remove = (label: string) => {
    void onSave(labels.filter((l) => l !== label));
  };

  const add = () => {
    const value = draft.trim();
    setDraft("");
    if (!value || labels.includes(value)) return;
    void onSave([...labels, value]);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    }
  };

  return (
    <div className="label-editor">
      {labels.map((label) => (
        <span
          key={label}
          className={`label-editor__chip label-chip label-chip--${labelColor(label)}`}
        >
          {label}
          <button
            type="button"
            className="label-editor__remove"
            aria-label={`remove ${label}`}
            onClick={() => remove(label)}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        className="label-editor__input"
        placeholder="add label…"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}

export default LabelEditor;
