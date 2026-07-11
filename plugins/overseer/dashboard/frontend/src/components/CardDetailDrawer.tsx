import { useCallback, useEffect, useRef, useState } from "react";
import { getCard } from "../api/client";
import type { CardDetail } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import BudgetMeter from "./BudgetMeter";
import PrioritySelect from "./PrioritySelect";
import LinkEditor from "./LinkEditor";
import StatusMenu from "./StatusMenu";

export interface CardDetailDrawerProps {
  /** Card id to show, or null when the drawer is closed. */
  cardId: string | null;
  onClose: () => void;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** All card ids on the board — threaded down to LinkEditor for its
   * parent/dependency option lists (see wf005-c6-brief.md). */
  allCardIds: string[];
}

/**
 * Sensible display order for well-known sections — anything else present in
 * `sections` is rendered too, just appended after these (see wf005-c5-brief.md:
 * "render whatever sections exist — do not hardcode a fixed set that hides
 * unknown headings").
 */
const PREFERRED_SECTION_ORDER = [
  "## Goal",
  "## Plan",
  "## Decisions",
  "## Progress log",
  "## Review log",
  "## Verification",
];

function orderedSectionEntries(
  sections: Record<string, string>
): [string, string][] {
  const keys = Object.keys(sections);
  const preferred = PREFERRED_SECTION_ORDER.filter((k) => keys.includes(k));
  const rest = keys.filter((k) => !PREFERRED_SECTION_ORDER.includes(k));
  return [...preferred, ...rest].map((k) => [k, sections[k]]);
}

function sectionLabel(heading: string): string {
  return heading.replace(/^#+\s*/, "");
}

/**
 * Read-only expand-to-view drawer (Chunk 5). Fetches `getCard(id)` lazily
 * into its OWN state — the board is never touched by opening/closing this.
 *
 * Carries the SAME monotonic-counter discipline as `useBoard.mutate` (see
 * wf005-context.md "Single mutation entrypoint" + the C5 brief's "counter-
 * guarded refetch" amendment): a stale/out-of-order `getCard` response (the
 * user reopens a different card before the first resolves, or a later
 * refetch — added in C6 — resolves first) is dropped; only the latest
 * issued request's result is ever applied.
 *
 * C6 adds the mutation controls (PrioritySelect/LinkEditor/StatusMenu). Each
 * routes its own call through `useBoard().mutate` (passed down from `App`)
 * — this component never calls the api client + setState for a mutation
 * itself. After any of those mutations settles, the control invokes
 * `onMutated` (wired to `refetchDetail` below) so the drawer's OWN view
 * re-fetches too, through the same counter guard — the board refresh from
 * `mutate` and this card-detail refetch are separate concerns.
 */
function CardDetailDrawer({
  cardId,
  onClose,
  mutate,
  inFlight,
  allCardIds,
}: CardDetailDrawerProps) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Monotonic counter, same pattern as useBoard's requestIdRef: a response is
  // only applied if its id is still the latest issued when it resolves.
  const requestIdRef = useRef(0);

  const fetchDetail = useCallback((id: string) => {
    const reqId = ++requestIdRef.current;
    setLoading(true);
    setError(null);

    getCard(id)
      .then((res) => {
        if (reqId !== requestIdRef.current) return; // stale — a newer open/refetch won
        setDetail(res);
      })
      .catch((e) => {
        if (reqId !== requestIdRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (reqId === requestIdRef.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (cardId === null) return;
    fetchDetail(cardId);
  }, [cardId, fetchDetail]);

  // Re-fetch the currently-open card, through the same counter guard —
  // passed to the mutation controls as `onMutated`.
  const refetchDetail = useCallback(() => {
    if (cardId !== null) fetchDetail(cardId);
  }, [cardId, fetchDetail]);

  useEffect(() => {
    if (cardId === null) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [cardId, onClose]);

  if (cardId === null) return null;

  const sectionEntries = detail ? orderedSectionEntries(detail.sections) : [];

  return (
    <div className="drawer-overlay" data-testid="drawer-overlay" onClick={onClose}>
      <aside
        className="card-drawer"
        role="dialog"
        aria-label={detail ? `${detail.id} details` : `${cardId} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="card-drawer__close"
          onClick={onClose}
          aria-label="Close"
        >
          ×
        </button>

        {loading && <p className="card-drawer__status">Loading…</p>}
        {error && (
          <p className="card-drawer__status card-drawer__status--error">
            {error}
          </p>
        )}

        {!loading && !error && detail && (
          <>
            <header className="card-drawer__header">
              <span className="card-drawer__id">{detail.id}</span>
              <h2 className="card-drawer__title">{detail.title}</h2>
              <div className="card-drawer__facts">
                <span className="card-drawer__status-fact">
                  {detail.status}
                  {detail.stage ? ` · ${detail.stage}` : ""}
                </span>
                <PrioritySelect
                  cardId={detail.id}
                  value={detail.priority}
                  mutate={mutate}
                  inFlight={inFlight}
                  onMutated={refetchDetail}
                />
                <BudgetMeter budget={detail.budget} />
              </div>
            </header>

            <div className="card-drawer__controls">
              <StatusMenu
                cardId={detail.id}
                status={detail.status}
                mutate={mutate}
                inFlight={inFlight}
                onMutated={refetchDetail}
              />
              <LinkEditor
                cardId={detail.id}
                parent={detail.parent}
                dependsOn={detail.depends_on}
                allCardIds={allCardIds}
                mutate={mutate}
                inFlight={inFlight}
                onMutated={refetchDetail}
              />
            </div>

            <div className="card-drawer__body">
              {sectionEntries.length > 0 ? (
                sectionEntries.map(([heading, text]) => (
                  <section key={heading} className="card-drawer__section">
                    <h3 className="card-drawer__section-heading">
                      {sectionLabel(heading)}
                    </h3>
                    <p className="card-drawer__section-text">{text}</p>
                  </section>
                ))
              ) : (
                <p className="card-drawer__section-text">{detail.body}</p>
              )}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

export default CardDetailDrawer;
