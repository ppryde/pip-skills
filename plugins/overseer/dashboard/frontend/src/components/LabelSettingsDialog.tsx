import { useEffect } from "react";
import { setLabelColor } from "../api/client";
import { labelColor, PALETTE_KEYS } from "../board/labelColor";
import type { UseBoardResult } from "../board/useBoard";

export interface LabelSettingsDialogProps {
  open: boolean;
  onClose: () => void;
  /** Every distinct label on the board (`board/cardFilter`'s
   * `distinctLabels`) — one settings row per label, TopBar-supplied. */
  labels: string[];
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`.
   * Read directly (never mutated locally): each row's current chip and
   * "selected" swatch both derive straight from this prop, same
   * deferred-state pattern as `LabelEditor`/`PrioritySelect` — no shadow
   * copy, `colors` is always the caller's source of truth. */
  colors: Record<string, string>;
  mutate: UseBoardResult["mutate"];
}

/**
 * F10 (WF-067) editable label colour registry settings dialog — opened from
 * TopBar. Rides the same `.party-overlay`/`.party-sheet` backdrop convention
 * as ClearDialog/NewCardDialog: outer overlay closes on click, inner sheet
 * stops propagation so clicking inside never closes it, Escape closes from
 * anywhere (only wired while `open`, mirroring NewCardDialog rather than
 * ClearDialog's always-open-while-mounted variant — this dialog is likewise
 * always mounted with `open` toggling visibility, not conditionally
 * rendered by its parent).
 *
 * One row per label: the label's current chip (`labelColor` — registry hit
 * or curated-palette hash fallback, identical resolution to every other
 * chip on the board), the 9 curated-palette swatches as pickable buttons,
 * and a Reset. Every mutation routes through the single `mutate`
 * entrypoint (wf005-context.md "Single mutation entrypoint") — no bare
 * `setLabelColor` call and no local optimistic colour state; a picked
 * swatch or Reset only ever shows once the refreshed `board.label_colors`
 * comes back through `colors`.
 */
function LabelSettingsDialog({
  open,
  onClose,
  labels,
  colors,
  mutate,
}: LabelSettingsDialogProps) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  async function pick(name: string, key: string) {
    await mutate(() => setLabelColor(name, key));
  }

  async function reset(name: string) {
    await mutate(() => setLabelColor(name, null));
  }

  return (
    <div className="party-overlay" onClick={onClose}>
      <div
        className="party-sheet label-settings-dialog"
        role="dialog"
        aria-label="Label colors"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="party-sheet__close"
          onClick={onClose}
          aria-label="Close"
        >
          ×
        </button>
        <h2 className="label-settings-dialog__title">Label colors</h2>
        {labels.length === 0 ? (
          <p className="label-settings-dialog__empty">
            No labels on this board yet.
          </p>
        ) : (
          labels.map((name) => {
            const current = colors[name];
            return (
              <div key={name} className="label-settings-row">
                <span
                  className={`label-chip label-chip--${labelColor(name, colors)}`}
                >
                  {name}
                </span>
                <div className="label-settings-row__swatches">
                  {PALETTE_KEYS.map((key) => (
                    <button
                      key={key}
                      type="button"
                      className={`label-settings-swatch label-chip--${key}`}
                      aria-label={`${name}: ${key}`}
                      aria-pressed={current === key}
                      onClick={() => void pick(name, key)}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  className="label-settings-row__reset"
                  onClick={() => void reset(name)}
                >
                  Reset
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default LabelSettingsDialog;
