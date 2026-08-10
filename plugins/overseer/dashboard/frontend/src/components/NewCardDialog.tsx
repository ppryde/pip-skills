import { useEffect, useState } from "react";
import { createCard } from "../api/client";
import type { CreateCardBody } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";

export interface NewCardDialogProps {
  open: boolean;
  onClose: () => void;
  /** Task 10: the create MUST route through this — same single mutation
   *  entrypoint every other control uses (see ThresholdControl's doc
   *  comment / wf005-context.md "Single mutation entrypoint"). No bare
   *  `createCard` call outside `mutate`, and no separate `onCreated`
   *  refresh callback: `createCard`'s response extends `BoardResponse`, so
   *  `mutate(() => createCard(body))` both creates the card and applies the
   *  refreshed board tiles in one round trip. */
  mutate: UseBoardResult["mutate"];
}

/**
 * "＋ New card" modal (Task 10, TopBar-owned open state). Rides the same
 * `.party-overlay`/`.party-sheet` backdrop convention as ClearDialog/
 * PartyOverlay — outer overlay closes on click, inner sheet stops
 * propagation so clicking inside never closes it, Escape closes from
 * anywhere. Unlike ClearDialog (whose `clearRepo` response isn't a
 * `BoardResponse`, so it can't go through `mutate` and instead calls the
 * client directly), this dialog's create is `mutate`-routed per the
 * single-entrypoint constraint above.
 */
function NewCardDialog({ open, onClose, mutate }: NewCardDialogProps) {
  const [title, setTitle] = useState("");
  const [complexity, setComplexity] = useState("");
  const [labels, setLabels] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const titleTrimmed = title.trim();

  async function submit() {
    if (!titleTrimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: CreateCardBody = { title: titleTrimmed };
      if (complexity) body.complexity = complexity;
      const labelList = labels
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (labelList.length > 0) body.labels = labelList;
      if (goal.trim()) body.goal = goal.trim();

      await mutate(() => createCard(body));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="party-overlay" onClick={onClose}>
      <div
        className="party-sheet new-card-dialog"
        role="dialog"
        aria-label="New card"
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
        <h2 className="new-card-dialog__title">New card</h2>
        <label className="new-card-field">
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
            autoFocus
          />
        </label>
        <label className="new-card-field">
          Complexity
          <select
            value={complexity}
            onChange={(e) => setComplexity(e.target.value)}
            disabled={busy}
          >
            <option value="">—</option>
            <option value="S">S</option>
            <option value="M">M</option>
            <option value="L">L</option>
            <option value="XL">XL</option>
          </select>
        </label>
        <label className="new-card-field">
          Labels
          <input
            value={labels}
            onChange={(e) => setLabels(e.target.value)}
            placeholder="comma, separated"
            disabled={busy}
          />
        </label>
        <label className="new-card-field">
          Goal
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            disabled={busy}
          />
        </label>
        {error && (
          <p className="new-card-error" role="alert">
            {error}
          </p>
        )}
        <div className="new-card-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy || !titleTrimmed}
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}

export default NewCardDialog;
