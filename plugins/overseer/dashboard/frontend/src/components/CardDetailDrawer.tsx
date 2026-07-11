import { useEffect, useRef, useState } from "react";
import { getCard } from "../api/client";
import type { CardDetail } from "../api/types";
import BudgetMeter from "./BudgetMeter";

export interface CardDetailDrawerProps {
  /** Card id to show, or null when the drawer is closed. */
  cardId: string | null;
  onClose: () => void;
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
 */
function CardDetailDrawer({ cardId, onClose }: CardDetailDrawerProps) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Monotonic counter, same pattern as useBoard's requestIdRef: a response is
  // only applied if its id is still the latest issued when it resolves.
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (cardId === null) return;

    const id = ++requestIdRef.current;
    setLoading(true);
    setError(null);

    getCard(cardId)
      .then((res) => {
        if (id !== requestIdRef.current) return; // stale — a newer open won
        setDetail(res);
      })
      .catch((e) => {
        if (id !== requestIdRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (id === requestIdRef.current) setLoading(false);
      });
  }, [cardId]);

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
    <div className="drawer-overlay" onClick={onClose}>
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
                {detail.priority && (
                  <span
                    className={`priority-chip priority-chip--${detail.priority}`}
                  >
                    {detail.priority}
                  </span>
                )}
                <BudgetMeter budget={detail.budget} />
              </div>
            </header>

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
