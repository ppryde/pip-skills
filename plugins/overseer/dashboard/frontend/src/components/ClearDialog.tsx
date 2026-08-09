import { useEffect, useState } from "react";
import { clearRepo } from "../api/client";
import type { ClearResponse } from "../api/types";

export interface ClearDialogProps {
  repoLabel: string;
  repoRoot: string;
  cardCount: number;
  onClose: () => void;
  onCleared: (res: ClearResponse) => void;
}

/**
 * Two-step "dragons" confirmation modal for the destructive clear-data
 * action (dashboard settings). Follows PartyOverlay's backdrop convention:
 * outer `.party-overlay` closes on click, inner `.party-sheet` (`role`
 * `dialog`) stops propagation so clicking inside never closes it, and
 * Escape closes from either step.
 *
 * Step 1 picks the scope (`repo` full-clear default, or `cards`-only) and
 * previews what will be removed, always noting the recovery snapshot taken
 * first (`overseer restore` undoes it). Step 2 is the actual "dragons" gate:
 * the destructive action only unlocks once the operator has typed the
 * exact, case-sensitive repo label — a deliberate speed bump, not a real
 * security boundary. `busy` disables both the retype-guard and the Back
 * button while the request is in flight so a slow clear can't be
 * double-fired or abandoned mid-flight.
 */
function ClearDialog({
  repoLabel,
  repoRoot,
  cardCount,
  onClose,
  onCleared,
}: ClearDialogProps) {
  const [step, setStep] = useState<1 | 2>(1);
  const [scope, setScope] = useState<"cards" | "repo">("repo");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  async function slay() {
    setBusy(true);
    setError(null);
    try {
      const res = await clearRepo(repoRoot, scope);
      onCleared(res);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const scopeSummary =
    scope === "repo"
      ? `everything for "${repoLabel}" (board, sprints, usage, and knowledge)`
      : `all ${cardCount} card(s) for "${repoLabel}" (identity kept)`;

  return (
    <div className="party-overlay" onClick={onClose}>
      <div
        className="party-sheet clear-dialog"
        role="dialog"
        aria-label="Clear repository data"
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

        {step === 1 ? (
          <>
            <h2 className="clear-dialog__title">
              🐉 Dragons be here — are you sure you wish to proceed?
            </h2>
            <fieldset className="clear-scope">
              <legend>What to clear</legend>
              <label>
                <input
                  type="radio"
                  name="scope"
                  checked={scope === "repo"}
                  onChange={() => setScope("repo")}
                />{" "}
                Everything (full repo folder)
              </label>
              <label>
                <input
                  type="radio"
                  name="scope"
                  checked={scope === "cards"}
                  onChange={() => setScope("cards")}
                />{" "}
                Cards only ({cardCount})
              </label>
            </fieldset>
            <p>This will remove {scopeSummary}.</p>
            <p>
              A recovery snapshot will be taken first — undo with{" "}
              <code>overseer restore</code>.
            </p>
            <div className="clear-actions">
              <button type="button" onClick={onClose}>
                Turn back
              </button>
              <button
                type="button"
                className="danger"
                onClick={() => setStep(2)}
              >
                Press on
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 className="clear-dialog__title">Very. Big. Dragons!</h2>
            <p>
              To confirm, type the repo label <strong>{repoLabel}</strong>{" "}
              below.
            </p>
            <label className="clear-confirm-label">
              Type the repo label
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                disabled={busy}
                autoFocus
              />
            </label>
            {error && (
              <p className="clear-error" role="alert">
                {error}
              </p>
            )}
            <div className="clear-actions">
              <button
                type="button"
                onClick={() => setStep(1)}
                disabled={busy}
              >
                Back
              </button>
              <button
                type="button"
                className="danger"
                disabled={typed !== repoLabel || busy}
                onClick={slay}
              >
                {busy ? "Slaying…" : "Slay it"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default ClearDialog;
