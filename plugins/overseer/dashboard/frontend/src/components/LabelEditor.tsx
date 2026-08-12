import { useState, type KeyboardEvent } from "react";
import { labelColor } from "../board/labelColor";
import { Chip } from "../ui";

export interface LabelEditorProps {
  labels: string[];
  /** Full-replace semantics, same as the backend's `POST /api/card/{id}/labels`
   * (via the existing `setLabels` client call) — always called with the
   * COMPLETE new label set, never a delta. */
  onSave: (labels: string[]) => Promise<void>;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * threaded through to `labelColor` so an edited label keeps its
   * registry-chosen colour, not just the hash-palette fallback. */
  colorRegistry?: Record<string, string>;
}

/**
 * WF-097 follow-up: the one control here that could route through the
 * design library, the per-chip remove "×", is DELIBERATELY left as a bare
 * `<button>` — `.label-editor__remove` is a small round icon-only glyph
 * (border: none, transparent fill, opacity-fade hover), the same bespoke
 * shape as `.link-editor__deps-list button` (LinkEditor.tsx), not a `.qb-btn`
 * rectangular Role-A button. Forcing it onto `<Button/>` would paint over
 * that shape with the wrong chrome entirely.
 *
 * Editable label control (F1 fold-in, WF-058) — chips with a per-chip remove
 * plus an add-input that commits on Enter. Every mutation (add/remove) calls
 * `onSave` with the full new set immediately; there is no separate "save"
 * step and no local optimistic label state — `labels` always reflects the
 * caller's source of truth, same pattern as the drawer's other mutation
 * controls (PrioritySelect/StatusMenu/LinkEditor) deferring to their own
 * props rather than tracking a shadow copy.
 *
 * Each chip routes through the design-library `<Chip/>` (`src/ui/`), same
 * `tone`/`className="label-chip"` composition `LabelChips` uses — so an
 * edited label keeps the SAME `.label-chip label-chip--<key>` classes and
 * established colour (`board/labelColor.ts`'s stable hash) it always has.
 * `.label-editor__chip` in styles.css only adds the layout needed to sit the
 * remove glyph inline, it never overrides the palette itself.
 */
function LabelEditor({ labels, onSave, colorRegistry }: LabelEditorProps) {
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
        <Chip
          key={label}
          tone={labelColor(label, colorRegistry)}
          className="label-editor__chip label-chip"
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
        </Chip>
      ))}
      <label className="label-editor__add">
        <span className="label-editor__add-plus" aria-hidden="true">
          +
        </span>
        <input
          type="text"
          className="label-editor__input"
          placeholder="label"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
        />
      </label>
    </div>
  );
}

export default LabelEditor;
