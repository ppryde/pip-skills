import { useEffect, useState } from "react";
import { setAttributes } from "../api/client";
import type { AttributesBody } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import { Button, Input, Label } from "../ui";

export interface AttributesEditorProps {
  cardId: string;
  sprint: string | null;
  /** The card's token estimate (`budget.estimate`), raw. */
  estimate: number | null;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  onMutated?: () => void;
}

const TOKENS_RE = /^(\d+(?:\.\d+)?)\s*([kKmM])?$/;

/** "400k" → 400000, "1.2M" → 1200000, "999" → 999; "" → null; else
 * undefined (unparseable). Mirrors the CLI's `parse_tokens`. */
export function parseTokens(raw: string): number | null | undefined {
  const text = raw.trim();
  if (text === "") return null;
  const m = TOKENS_RE.exec(text);
  if (!m) return undefined;
  const mult = { k: 1_000, m: 1_000_000 }[(m[2] ?? "").toLowerCase()] ?? 1;
  return Math.round(parseFloat(m[1]) * mult);
}

/** The estimate as a person would type it back: 400000 → "400k". */
function showTokens(n: number | null): string {
  if (n === null) return "";
  if (n >= 1_000_000 && n % 100_000 === 0) return `${n / 1_000_000}M`;
  if (n >= 1_000 && n % 1_000 === 0) return `${n / 1_000}k`;
  return String(n);
}

/**
 * WF-070: sprint + token estimate, editable from the drawer. Two free-text
 * fields and one Save that sends ONLY what changed (`null` to clear), so an
 * untouched field is never rewritten. Routes through `useBoard().mutate`
 * like every other drawer control.
 */
function AttributesEditor({ cardId, sprint, estimate, mutate, inFlight, onMutated }: AttributesEditorProps) {
  const [sprintText, setSprintText] = useState(sprint ?? "");
  const [estimateText, setEstimateText] = useState(showTokens(estimate));
  const [error, setError] = useState<string | null>(null);
  // A refetch (or another card) resets the drafts to what the card holds.
  useEffect(() => {
    setSprintText(sprint ?? "");
    setEstimateText(showTokens(estimate));
    setError(null);
  }, [cardId, sprint, estimate]);

  const nextSprint = sprintText.trim() === "" ? null : sprintText.trim();
  const nextEstimate = parseTokens(estimateText);
  const sprintChanged = nextSprint !== (sprint ?? null);
  const estimateChanged = nextEstimate !== undefined && nextEstimate !== estimate;
  const dirty = sprintChanged || estimateChanged;

  async function save() {
    if (nextEstimate === undefined) {
      setError("Estimate should be a token count like 400k or 1.2M.");
      return;
    }
    const body: AttributesBody = {};
    if (sprintChanged) body.sprint = nextSprint;
    if (estimateChanged) body.estimate = nextEstimate;
    if (Object.keys(body).length === 0) return;
    setError(null);
    await mutate(() => setAttributes(cardId, body));
    onMutated?.();
  }

  return (
    <form
      className="attributes-editor"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label className="attributes-editor__field">
        <Label>Sprint</Label>
        <Input
          aria-label="Sprint"
          value={sprintText}
          onChange={(e) => setSprintText(e.target.value)}
          placeholder="— none —"
          disabled={inFlight}
        />
      </label>
      <label className="attributes-editor__field">
        <Label>Estimate</Label>
        <Input
          aria-label="Estimate"
          value={estimateText}
          onChange={(e) => setEstimateText(e.target.value)}
          placeholder="e.g. 400k"
          disabled={inFlight}
          aria-invalid={nextEstimate === undefined || undefined}
        />
      </label>
      {/* "Apply", not "Save": the drawer's title/body edit mode owns "Save". */}
      <Button type="submit" disabled={inFlight || !dirty}>
        Apply
      </Button>
      {error && (
        <p className="attributes-editor__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default AttributesEditor;
